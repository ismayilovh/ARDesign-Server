"""
Celery tasks for 3D model conversion and generation.

Two independent flows:

convert_patent_task (queue: convert, concurrency=1)
  Takes an uploaded ZIP, runs it through the configured ephemeral converter
  container via DooD, produces a GLB. See convert_patent_task docstring.

generate_from_image_task (queue: generate, concurrency=1)
  Takes one-or-more view images already on the media volume, posts them to
  the host-native Hunyuan3D API server, writes the returned GLB back to the
  media volume. Serialized at the queue level because a single GPU cannot
  run two generations in parallel.
"""
import base64
import json
import logging
import os
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

import requests

from app.core.config import settings
from app.db.sync_session import SyncSessionLocal
from app.models.patent import ConversionStatus, ModelScale, Patent
from app.worker.celery_app import CONVERTER_IMAGE, celery_app

logger = logging.getLogger(__name__)

# Extensions that the converter accepts
MODEL_EXTENSIONS = {".obj", ".stl", ".stp", ".iges", ".glb", ".fbx"}

# Resource limits for the ephemeral converter container
CONTAINER_MEMORY = "12g"
CONTAINER_CPUS = "1.5"
CONTAINER_PIDS = "512"
CONTAINER_TIMEOUT = 600  # seconds

# main.py expects the unit as lowercase ('mm'/'cm'/'in'/'m'); the DB enum is
# uppercase like every other enum in the project. Translate at the call site
# so the wire/DB representation stays uppercase.
_SCALE_TO_CLI: dict[ModelScale, str] = {
    ModelScale.MM: "mm",
    ModelScale.CM: "cm",
    ModelScale.IN: "in",
    ModelScale.M: "m",
}

# ---------------------------------------------------------------------------
# Shell scripts that run INSIDE the ephemeral container.
# $1 is the only user-controlled value — passed as a positional argument,
# never interpolated into the script text.
# ---------------------------------------------------------------------------

_EXTRACT = (
    '/app/converter/venv/bin/python3.11 -c "'
    "import zipfile, os; "
    "os.makedirs('/tmp/work', exist_ok=True); "
    "zipfile.ZipFile('/tmp/model.zip').extractall('/tmp/work')"
    '"'
)

# For models that need conversion (OBJ/STL/STP/IGES/FBX).
# $1 = absolute path to the model file inside /tmp/work.
# $2 = source unit string (mm/cm/in/m) — main.py's second positional arg.
# FBX converter does os.chdir(/app/converter/) so output.glb may land there;
# we try /tmp/work first, fall back to /app/converter/.
#
# We do NOT chain the converter command with && : the FBX path uses bpy,
# which finishes writing output.glb successfully and then SIGSEGVs during
# Python interpreter shutdown because the surrounding container is being
# torn down at the same time. The crash is cosmetic — the GLB is already
# on disk. We check for the file itself, ignoring Python's exit code, so
# those shutdown crashes don't discard real conversions.
CONVERT_SCRIPT = (
    "set -e\n"
    f"{_EXTRACT}\n"
    "cd /tmp/work\n"
    "set +e\n"
    "xvfb-run -a /app/converter/venv/bin/python3.11 "
    '/app/converter/main.py "$1" "$2"\n'
    "PYCODE=$?\n"
    "mkdir -p /output\n"
    # Soft-warning JSONs are written to the converter's CWD: OBJ runs from
    # /tmp/work, FBX chdirs to /app/converter mid-script. Both files are
    # optional — copy only the ones that exist; missing means no warnings.
    "for d in /tmp/work /app/converter; do\n"
    '  for f in import_errors.json export_errors.json; do\n'
    '    if [ -f "$d/$f" ]; then cp "$d/$f" "/output/$f"; fi\n'
    "  done\n"
    "done\n"
    "if [ -f /tmp/work/output.glb ]; then "
    "cp /tmp/work/output.glb /output/output.glb; exit 0; fi\n"
    "if [ -f /app/converter/output.glb ]; then "
    "cp /app/converter/output.glb /output/output.glb; exit 0; fi\n"
    'echo "Converter produced no output.glb (python exited $PYCODE)" >&2\n'
    "exit ${PYCODE:-1}\n"
)


def _find_model_file_in_zip(zip_abs_path: str) -> str:
    """Return the in-archive path of the first recognised 3-D model file."""
    with zipfile.ZipFile(zip_abs_path) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            if os.path.splitext(name)[1].lower() in MODEL_EXTENSIONS:
                return name
    raise ValueError(f"No supported model file found in {zip_abs_path}")


def _docker(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a docker CLI command via the mounted socket."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _converter_create_cmd(
    container_name: str, script: str, script_args: list[str]
) -> list[str]:
    """Build the `docker create` argv for an ephemeral, hardened converter
    container that runs `bash -c <script> _ <script_args...>`.

    Centralizes the resource limits + security hardening so the converter and
    the thumbnailer can't drift apart (same single-source-of-truth reasoning
    that keeps CONVERTER_IMAGE in celery_app). The script_args become $1, $2…
    positional data args — never interpolated into the script text, so they're
    unreachable by shell injection."""
    return [
        "docker", "create",
        "--name", container_name,
        "--init",
        # Resource limits
        "--memory", CONTAINER_MEMORY,
        "--memory-swap", CONTAINER_MEMORY,   # no swap beyond memory limit
        "--cpus", CONTAINER_CPUS,
        "--pids-limit", CONTAINER_PIDS,
        # Security hardening
        "--network", "none",                 # no network access
        "--cap-drop", "ALL",                 # drop all Linux capabilities
        "--security-opt", "no-new-privileges",
        # Entrypoint
        "--entrypoint", "bash",
        CONVERTER_IMAGE,
        "-c", script, "_", *script_args,
        #     ^^^^^^       ^^^^^^^^^^^
        #     script text  $1, $2... = data args (safe from injection)
    ]


def _collect_converter_warnings(container_name: str) -> list[dict]:
    """Pull import_errors.json / export_errors.json out of the container,
    tag each entry with its phase, and return a merged list. Missing or
    unparseable files are silently treated as 'no warnings' — these are soft
    diagnostics, not a reason to fail an otherwise-successful conversion."""
    merged: list[dict] = []
    for phase, fname in (("import", "import_errors.json"), ("export", "export_errors.json")):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cp = _docker(
                ["docker", "cp", f"{container_name}:/output/{fname}", tmp_path],
            )
            if cp.returncode != 0:
                continue  # file didn't exist in /output → no warnings of this phase
            with open(tmp_path, encoding="utf-8") as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                merged.append({
                    "phase": phase,
                    "message": entry.get("message", ""),
                    "details": entry.get("details", ""),
                })
        except (OSError, ValueError) as exc:
            logger.warning("Could not parse %s from container %s: %s",
                           fname, container_name, exc)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return merged


@celery_app.task(bind=True, max_retries=0, name="convert_patent")
def convert_patent_task(self, patent_id: int) -> None:
    db = SyncSessionLocal()
    patent: Patent | None = None
    container_name = f"converter-{patent_id}-{uuid.uuid4().hex[:8]}"

    try:
        patent = db.get(Patent, patent_id)
        if not patent:
            logger.error("convert_patent_task: patent %d not found", patent_id)
            return

        # -- 1. Mark as in-flight ------------------------------------------------
        patent.conversion_status = ConversionStatus.CONVERTING
        patent.conversion_error = None
        db.commit()

        # -- 2. Locate the model file inside the stored ZIP ----------------------
        zip_abs_path = os.path.join(settings.media_root, patent.zip_file_path)
        model_in_zip = _find_model_file_in_zip(zip_abs_path)

        # -- 3. Build output path on the worker's media volume -------------------
        # Use the design name (already filesystem-sanitized at upload time) so
        # the on-disk path mirrors what the user sees in the UI. Fall back to
        # the in-zip stem for legacy patents created before the registration
        # form existed.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        stem = patent.model_filename or os.path.splitext(os.path.basename(model_in_zip))[0]
        glb_dir_rel = f"converted/user_{patent.user_id}/{timestamp}_{stem}"
        glb_rel = f"{glb_dir_rel}/output.glb"

        # -- 4. Build positional arguments ---------------------------------------
        # model_arg is passed as $1, scale_arg as $2 — never interpolated into
        # the script text, so neither is reachable by shell injection.
        model_arg = f"/tmp/work/{model_in_zip}"
        scale_arg = _SCALE_TO_CLI[ModelScale(patent.scale)]

        script = CONVERT_SCRIPT
        script_args = [model_arg, scale_arg]

        # -- 5. Create container (no volume mounts — fully isolated) -------------
        create_cmd = _converter_create_cmd(container_name, script, script_args)

        logger.info("Creating converter container %s for patent %d",
                     container_name, patent_id)
        _docker(create_cmd, check=True)

        # -- 6. Copy ZIP into the stopped container ------------------------------
        _docker(
            ["docker", "cp", zip_abs_path, f"{container_name}:/tmp/model.zip"],
            check=True,
        )

        # -- 7. Start container and block until it exits -------------------------
        result = _docker(
            ["docker", "start", "-a", container_name],
            timeout=CONTAINER_TIMEOUT,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Converter exited {result.returncode}.\n"
                f"stdout: {result.stdout[-1000:]}\n"
                f"stderr: {result.stderr[-1000:]}"
            )

        # -- 8. Copy GLB out of the container onto the media volume --------------
        glb_abs = os.path.join(settings.media_root, glb_rel)
        os.makedirs(os.path.dirname(glb_abs), exist_ok=True)

        _docker(
            ["docker", "cp", f"{container_name}:/output/output.glb", glb_abs],
            check=True,
        )

        if not os.path.exists(glb_abs):
            raise FileNotFoundError(f"Expected GLB not found at {glb_abs}")

        # -- 9. Pull soft warnings (optional) ------------------------------------
        warnings = _collect_converter_warnings(container_name)
        if warnings:
            logger.info("Patent %d converted with %d warning(s)",
                         patent_id, len(warnings))

        # -- 10. Persist GLB, then hand off to the thumbnailer -------------------
        # The patent stays CONVERTING here: generate_thumbnail_task makes the
        # final flip to CONVERTED (best-effort) so a model is only marked
        # "ready" once we've at least *tried* to render its thumbnail. A
        # thumbnail failure still lands the patent on CONVERTED — see that task.
        patent.glb_file_path = glb_rel
        patent.conversion_warnings = warnings or None
        db.commit()
        generate_thumbnail_task.delay(patent_id)
        logger.info("Patent %d converted -> %s; queued thumbnail render",
                     patent_id, glb_rel)

    except Exception as exc:
        logger.exception("Conversion failed for patent %d", patent_id)
        if patent:
            patent.conversion_status = ConversionStatus.FAILED
            patent.conversion_error = str(exc)[:2000]
            db.commit()
    finally:
        # Always remove the container, even on failure/timeout
        _docker(["docker", "rm", "-f", container_name])
        db.close()


# ---------------------------------------------------------------------------
# Thumbnail rendering (Blender inside the converter image)
# ---------------------------------------------------------------------------

# Local path to the headless Blender renderer we inject into the container.
# It ships beside this module; the container has no copy of its own.
_THUMBNAIL_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "thumbnail.py")

# Runs thumbnail.py against the GLB inside the container. $1 = input GLB path,
# $2 = output PNG path. Run from /app/converter for parity with the converter
# (that's where the bpy site/addon state lives). The Cycles-CPU render needs no
# GL context, but we keep xvfb-run for parity since some bpy operators still
# expect a window. `set -e` makes any render failure a non-zero exit, which the
# task treats as "no thumbnail" without blocking the model.
THUMBNAIL_SCRIPT = (
    "set -e\n"
    "mkdir -p /output\n"
    "cd /app/converter\n"
    "xvfb-run -a /app/converter/venv/bin/python3.11 /tmp/thumbnail.py \"$1\" \"$2\"\n"
)


@celery_app.task(bind=True, max_retries=0, name="generate_thumbnail")
def generate_thumbnail_task(self, patent_id: int) -> None:
    """Render a PNG thumbnail of a patent's converted GLB, then flip it to
    CONVERTED.

    Enqueued by convert_patent_task once the GLB is on disk. Both the upload and
    the image-generation pipelines funnel through that task, so this single hook
    covers both ingestion paths.

    Thumbnailing is best-effort: we try exactly once (max_retries=0) and the
    patent becomes available (CONVERTED) whether or not the render succeeds — a
    missing thumbnail must never gate an otherwise-finished model. The render
    runs in the same hardened, network-less converter container as conversion.
    """
    db = SyncSessionLocal()
    patent: Patent | None = None
    container_name = f"thumbnailer-{patent_id}-{uuid.uuid4().hex[:8]}"

    try:
        patent = db.get(Patent, patent_id)
        if not patent:
            logger.error("generate_thumbnail_task: patent %d not found", patent_id)
            return
        if not patent.glb_file_path:
            raise RuntimeError("patent has no glb_file_path to thumbnail")

        glb_abs = os.path.join(settings.media_root, patent.glb_file_path)
        if not os.path.exists(glb_abs):
            raise FileNotFoundError(f"GLB missing at {glb_abs}")

        # Thumbnail lives next to the GLB so delete_patent_files' glb-dir sweep
        # cleans it up for free.
        thumb_rel = f"{os.path.dirname(patent.glb_file_path)}/thumbnail.png"
        thumb_abs = os.path.join(settings.media_root, thumb_rel)

        create_cmd = _converter_create_cmd(
            container_name, THUMBNAIL_SCRIPT,
            ["/tmp/model.glb", "/output/thumbnail.png"],
        )
        logger.info("Creating thumbnailer container %s for patent %d",
                    container_name, patent_id)
        _docker(create_cmd, check=True)

        # Copy in the GLB plus the renderer script (the image has neither).
        _docker(["docker", "cp", glb_abs, f"{container_name}:/tmp/model.glb"],
                check=True)
        _docker(["docker", "cp", _THUMBNAIL_SCRIPT_PATH,
                 f"{container_name}:/tmp/thumbnail.py"], check=True)

        result = _docker(
            ["docker", "start", "-a", container_name], timeout=CONTAINER_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Thumbnailer exited {result.returncode}.\n"
                f"stdout: {result.stdout[-1000:]}\n"
                f"stderr: {result.stderr[-1000:]}"
            )

        os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)
        _docker(
            ["docker", "cp", f"{container_name}:/output/thumbnail.png", thumb_abs],
            check=True,
        )
        if not os.path.exists(thumb_abs):
            raise FileNotFoundError(f"Expected thumbnail not found at {thumb_abs}")

        patent.thumbnail_path = thumb_rel
        logger.info("Patent %d thumbnail rendered -> %s", patent_id, thumb_rel)

    except Exception:
        # Best-effort: log and fall through. The finally block still flips the
        # patent to CONVERTED so a thumbnail failure never blocks the model.
        logger.exception(
            "Thumbnail render failed for patent %d; making it available without one",
            patent_id,
        )
    finally:
        if patent:
            patent.conversion_status = ConversionStatus.CONVERTED
            db.commit()
        _docker(["docker", "rm", "-f", container_name])
        db.close()


# ---------------------------------------------------------------------------
# Image-to-3D generation via Hunyuan3D-2
# ---------------------------------------------------------------------------

# Inference defaults — mirror examples/textured_shape_gen_multiview.py.
# Individual requests can override via the `gen_overrides` task arg.
GEN_DEFAULTS: dict = {
    "texture": True,
    "num_inference_steps": 50,
    "octree_resolution": 380,
    "num_chunks": 20000,
    "type": "glb",
}

HUNYUAN_CONNECT_TIMEOUT = 30  # seconds to establish the TCP connection


def _load_image_b64(abs_path: str) -> str:
    with open(abs_path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


@celery_app.task(bind=True, max_retries=0, name="generate_from_image")
def generate_from_image_task(
    self, patent_id: int, gen_overrides: dict | None = None
) -> None:
    """
    Generate a GLB from one-or-more view images via the host-native Hunyuan3D
    API server. Uses /generate (sync) so errors surface immediately as HTTP 404
    with a descriptive body — /send swallows worker-thread errors silently.

    Preconditions on the Patent row:
      - file_type == IMAGE
      - storage_path points to the directory containing the view images
      - related_files is a dict mapping view label -> filename
        (e.g. {"front": "front.png", "left": "left.png"})

    `gen_overrides` is an optional dict merged on top of GEN_DEFAULTS — used by
    the /generate endpoint to plumb UI presets (quality, detail) into pipeline
    params (num_inference_steps, octree_resolution).
    """
    db = SyncSessionLocal()
    patent: Patent | None = None

    try:
        patent = db.get(Patent, patent_id)
        if not patent:
            logger.error("generate_from_image_task: patent %d not found", patent_id)
            return

        # -- 1. Mark as generating --------------------------------------------
        # Distinct from CONVERTING (which the converter uses) so the UI shows
        # GENERATING -> QUEUED -> CONVERTING -> CONVERTED rather than a
        # confusing repeated status across the two pipeline halves.
        patent.conversion_status = ConversionStatus.GENERATING
        patent.conversion_error = None
        db.commit()

        # -- 2. Load views and build multi-view payload -----------------------
        if not patent.storage_path or not isinstance(patent.related_files, dict):
            raise RuntimeError(
                "patent missing image set (storage_path/related_files)"
            )

        storage_abs = os.path.join(settings.media_root, patent.storage_path)
        images_b64: dict[str, str] = {}
        for view_name, filename in patent.related_files.items():
            img_path = os.path.join(storage_abs, filename)
            if not os.path.isfile(img_path):
                raise FileNotFoundError(f"missing view image: {img_path}")
            images_b64[view_name] = _load_image_b64(img_path)

        payload = {"images": images_b64, **GEN_DEFAULTS, **(gen_overrides or {})}

        # -- 3. Call Hunyuan /generate (sync, returns GLB bytes) --------------
        base_url = settings.hunyuan_base_url.rstrip("/")
        logger.info(
            "Patent %d: POST %s/generate with %d view(s): %s",
            patent_id, base_url, len(images_b64), list(images_b64.keys()),
        )
        resp = requests.post(
            f"{base_url}/generate",
            json=payload,
            timeout=(HUNYUAN_CONNECT_TIMEOUT, settings.hunyuan_total_timeout),
        )

        if resp.status_code == 200:
            glb_bytes = resp.content
        elif resp.status_code == 404:
            # Hunyuan's error convention: any failure returns 404 with
            # {"text": "<message>", "error_code": 1}. Not a missing endpoint.
            try:
                detail = resp.json().get("text", resp.text[:500])
            except ValueError:
                detail = resp.text[:500]
            raise RuntimeError(f"Hunyuan generation failed: {detail}")
        else:
            resp.raise_for_status()

        if not glb_bytes:
            raise RuntimeError("Hunyuan returned empty response body")

        # -- 4. Wrap the raw GLB in a ZIP so it flows through the very same
        #       converter pipeline as an uploaded GLB archive ----------------
        # Hunyuan's GLB is not the finished product: it still needs the
        # converter's post-processing (Blender import -> DRACO re-export). Rather
        # than duplicate the container plumbing here, we package the GLB as a ZIP,
        # point the patent at it, and hand off to convert_patent_task — the
        # generated patent then takes the identical path as a GLB upload.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        stem = patent.model_filename or f"generated_{patent.id}"
        zip_rel = f"uploads/user_{patent.user_id}/{timestamp}_generated_{stem}.zip"
        zip_abs = os.path.join(settings.media_root, zip_rel)
        os.makedirs(os.path.dirname(zip_abs), exist_ok=True)
        with zipfile.ZipFile(zip_abs, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{stem}.glb", glb_bytes)

        # -- 5. Hand off to the converter queue -------------------------------
        # Stays QUEUED (not CONVERTED) — generation is only half the pipeline now.
        # convert_patent_task runs on the default queue, so the single-GPU
        # `generate` worker is freed immediately instead of blocking on the
        # CPU/docker conversion.
        patent.zip_file_path = zip_rel
        patent.conversion_status = ConversionStatus.QUEUED
        db.commit()
        convert_patent_task.delay(patent_id)
        logger.info("Patent %d generated; queued for conversion -> %s",
                     patent_id, zip_rel)

    except Exception as exc:
        logger.exception("Generation failed for patent %d", patent_id)
        if patent:
            patent.conversion_status = ConversionStatus.FAILED
            patent.conversion_error = str(exc)[:2000]
            db.commit()
    finally:
        db.close()
