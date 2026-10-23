#!/usr/bin/env python3
"""Run the converter measurement protocol from measurement.pdf.

Input directory contains one model per file. A same-stem .json sidecar may
specify {"unit":"mm", "group":"OBJ", "expected_failure":false}.
Outputs are retained beneath --output and one CSV is written at --csv.
"""
import argparse
import csv
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


SUPPORTED = {".obj", ".stl", ".glb", ".gltf", ".fbx", ".stp", ".step", ".iges", ".igs"}
SCALE = {"mm": "mm", "cm": "cm", "in": "in", "m": "m"}
DEFAULT_GROUP = {".obj": "OBJ", ".stl": "STL", ".glb": "GLB/glTF",
                 ".gltf": "GLB/glTF", ".fbx": "FBX", ".stp": "CAD",
                 ".step": "CAD", ".iges": "CAD", ".igs": "CAD"}
FIELDS = ["file", "group", "unit", "format", "triangles", "result", "warnings",
          "expected_failure", "error", "conversion_seconds", "glb_no_draco_bytes", "glb_draco_bytes",
          "draco_reduction_percent", "source_bounds_m_x", "source_bounds_m_y",
          "source_bounds_m_z", "output_bounds_m_x", "output_bounds_m_y",
          "output_bounds_m_z", "bounds_max_difference_percent", "deviation_mean_mm",
          "deviation_max_mm", "notes"]


def run(args, *, check=False, capture=True):
    return subprocess.run(args, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def converter_script():
    return (
        "cd /app/converter\n"
        "set +e\n"
        "/app/converter/venv/bin/python3.11 -c 'import subprocess,time,sys; "
        "t=time.perf_counter(); p=subprocess.run([\"/app/converter/venv/bin/python3.11\","
        "\"/app/converter/main.py\",sys.argv[1],sys.argv[2]]); "
        "print(\"MEASURE_SECONDS=%0.6f\" % (time.perf_counter()-t), flush=True); sys.exit(p.returncode)' "
        "\"$1\" \"$2\"\n"
        "code=$?\n"
        "set -e\n"
        "mkdir -p /output\n"
        "for f in import_errors.json export_errors.json; do "
        "[ ! -f \"$f\" ] || cp \"$f\" /output/; done\n"
        "if [ $code -ne 0 ] || [ ! -f output.glb ]; then "
        "echo \"Converter failed (exit $code) or produced no output.glb\" >&2; exit ${code:-1}; fi\n"
        "/app/converter/venv/bin/python3.11 /tmp/measurement_export.py "
        "/app/converter/output.glb /output\n"
    )


def read_warning(container, name, phase):
    target = Path(name)
    cp = run(["docker", "cp", f"{container}:/output/{phase}_errors.json", str(target)])
    if cp.returncode:
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return [str(entry.get("message", entry)) for entry in data] if isinstance(data, list) else []
    except (OSError, ValueError):
        return [f"Could not parse {phase}_errors.json"]
    finally:
        target.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, help="Directory of individual source model files")
    parser.add_argument("--output", type=Path, default=Path("measurement-results"))
    parser.add_argument("--csv", type=Path, default=Path("measurement.csv"))
    parser.add_argument("--image", default=os.getenv("CONVERTER_IMAGE", "ismayilovh/ardesign-converter:latest"))
    parser.add_argument("--default-unit", choices=SCALE, default="m")
    parser.add_argument("--memory", default="12g")
    parser.add_argument("--cpus", default="1.5")
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    sources = sorted(p for p in ns.inputs.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
    if not sources:
        parser.error(f"No supported model files found in {ns.inputs}")
    rows = []
    for source in sources:
        meta_path = source.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        unit = str(meta.get("unit", ns.default_unit)).lower()
        if unit not in SCALE:
            raise SystemExit(f"{meta_path}: unit must be mm, cm, in, or m")
        group = meta.get("group", DEFAULT_GROUP[source.suffix.lower()])
        expected_failure = bool(meta.get("expected_failure", False))
        name = f"measurement-{uuid.uuid4().hex[:10]}"
        work = ns.output / source.stem
        work.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="ardesign-measure-"))
        row = dict.fromkeys(FIELDS, "")
        row.update(file=source.name, group=group, unit=unit, format=source.suffix.lstrip(".").upper(),
                   expected_failure=str(expected_failure).lower())
        try:
            run(["docker", "create", "--name", name, "--init", "--memory", ns.memory,
                 "--memory-swap", ns.memory, "--cpus", ns.cpus, "--pids-limit", "512",
                 "--network", "none", "--cap-drop", "ALL", "--security-opt",
                 "no-new-privileges", "--entrypoint", "bash", ns.image,
        "-c", converter_script(), "_", f"/tmp/input/{source.relative_to(source.parent).as_posix()}", unit], check=True)
            for candidate in source.parent.rglob("*"):
                if not candidate.is_file():
                    continue
                if candidate.suffix.lower() in SUPPORTED and candidate.resolve() != source.resolve():
                    continue
                relative = candidate.relative_to(source.parent)
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, target)
            run(["docker", "cp", str(stage.resolve()), f"{name}:/tmp/input"], check=True)
            run(["docker", "cp", str(Path(__file__).with_name("measurement_export.py").resolve()),
                 f"{name}:/tmp/measurement_export.py"], check=True)
            proc = run(["docker", "start", "-a", name])
            output_lines = (proc.stdout or "").splitlines()
            measured = [line.partition("=")[2] for line in output_lines
                        if line.startswith("MEASURE_SECONDS=")]
            if measured:
                row["conversion_seconds"] = measured[-1]
            if proc.returncode:
                message = (proc.stderr or proc.stdout or f"converter exited {proc.returncode}").strip()
                row["result"] = "failure"
                row["error"] = message[-2000:]
                warnings = read_warning(name, str(work / "warnings"), "import")
                warnings += read_warning(name, str(work / "warnings"), "export")
                row["warnings"] = " | ".join(warnings)
            else:
                inspect = run(["docker", "logs", name])
                try:
                    stats = json.loads(inspect.stdout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    raise RuntimeError("Converter succeeded but measurement JSON was missing")
                warnings = read_warning(name, str(work / "warnings"), "import")
                warnings += read_warning(name, str(work / "warnings"), "export")
                row.update(result="success with warnings" if warnings else "success",
                           warnings=" | ".join(warnings), triangles=stats["triangles"])
                bounds = stats.get("bounds_m")
                if bounds:
                    for axis, value in zip("xyz", bounds):
                        row[f"output_bounds_m_{axis}"] = f"{value:.9g}"
                sizes = stats["sizes_bytes"]
                row["glb_no_draco_bytes"] = sizes["no_draco"]
                row["glb_draco_bytes"] = sizes["draco"]
                row["draco_reduction_percent"] = f"{100*(1-sizes['draco']/sizes['no_draco']):.3f}" if sizes["no_draco"] else ""
                for variant in ("no_draco", "draco"):
                    run(["docker", "cp", f"{name}:/output/{variant}.glb", str(work / f"{variant}.glb")], check=True)
                row["notes"] = "Bounds report the converter output in meters; source bounds and deviation are recorded after the Blender reference comparison."
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, RuntimeError) as exc:
            row["result"] = "failure"
            row["error"] = str(exc)[-2000:]
        finally:
            run(["docker", "rm", "-f", name])
            shutil.rmtree(stage, ignore_errors=True)
        if expected_failure and row["result"] == "failure" and row["error"]:
            row["notes"] = "Expected malformed-input failure; review whether the message is actionable."
        elif expected_failure and row["result"] != "failure":
            row["notes"] = "Expected malformed input but converter did not fail; inspect output and warnings."
        rows.append(row)
        print(f"{source.name}: {row['result']} ({row['conversion_seconds']}s)")
    ns.csv.parent.mkdir(parents=True, exist_ok=True)
    with ns.csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV: {ns.csv.resolve()}")
    print(f"Host: {platform.platform()} | Python: {sys.version.split()[0]}")
    print("Source bounds and surface deviations remain blank for Blender/trimesh reference measurements.")


if __name__ == "__main__":
    main()
