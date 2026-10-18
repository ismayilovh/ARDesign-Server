# Converter image runtime contract

These notes describe the converter behavior observed in the original
`youndria/arpatent:1.5` image. The configured replacement is
`ismayilovh/ardesign-converter:latest`; it is intended to preserve the same
runtime contract. Re-check this document if that compatibility changes.

## TL;DR for `tasks.py`

- **Invocation:** `xvfb-run -a /app/converter/venv/bin/python3.11 /app/converter/main.py <ABS_INPUT_PATH> <SCALE>`
- **Run it from `/app/converter`** (`cd /app/converter` first). Do NOT `cd` elsewhere — see "Working directory matters" below.
- **Output:** always `output.glb` written to the **current working directory**
  (i.e. `/app/converter/output.glb` when run from there).
- **Scale arg:** one of `mm` / `cm` / `in` / `m` (lowercase). Unknown → defaults to meters with a warning.
- **Exit code is reliable now:** `0` = success, `1` = failure. The old FBX
  "SIGSEGV on interpreter shutdown" workaround is no longer needed — `main.py`
  ends with `os._exit(0)`, so there is no Python shutdown to crash. Trust the
  exit code; you don't have to fall back to "did output.glb appear".
- **Warnings:** optional `import_errors.json` / `export_errors.json` are written
  to the CWD (same dir as `output.glb`). Messages are **Turkish, user-facing**.

## GLB is now post-processed, not passed through

This is the change the friend made. `utils.py`:

```python
NONCAD_FILE_LIST = [".obj", ".stl", ".fbx", ".glb", ".gltf"]
CAD_FILE_LIST    = [".iges", ".igs", ".stp", ".step"]
```

`.glb` / `.gltf` now run through `process_glb_gltf()` in
`convert_non_cad_formats.py`: import into Blender → re-export as GLB **with DRACO
mesh compression**. So a GLB in → a smaller, normalized GLB out. That's why GLB
should go through the converter instead of being copied verbatim.

DRACO settings (shared by every export path):
`level=6`, quantization `position=16, normal=12, texcoord=20, generic=12`.

Note: the GLB/GLTF path does **not** call `resize_model()`, so the `<SCALE>`
arg is ignored for GLB/GLTF input (only OBJ/STL/FBX/CAD honor scale).

## Supported extensions (superset of what tasks.py currently allows)

| Extension | Path | Engine |
|-----------|------|--------|
| `.obj` | `convert_obj` | bpy (Blender) |
| `.stl` | `convert_stl` | bpy |
| `.fbx` | `convert_fbx.convert_fbx_to_glb` | ufbx + bpy |
| `.glb` `.gltf` | `process_glb_gltf` | bpy |
| `.iges` `.igs` `.stp` `.step` | `freecad_converter.py` | FreeCAD |

`tasks.py`'s `MODEL_EXTENSIONS` is currently `{.obj,.stl,.stp,.iges,.glb,.fbx}` —
it omits `.igs`, `.step`, and `.gltf` that the converter actually supports.

## Pipeline shape

```
main.py <input> <scale>
  └─ utils.convert_file_to_glb(input)
       ├─ ext in NONCAD → convert_non_cad(input, ext)   # bpy
       │     ├─ .obj  → convert_obj        (gamma fix, custom normals, resize, DRACO export)
       │     ├─ .stl  → convert_stl        (resize, DRACO export)
       │     ├─ .fbx  → convert_fbx_to_glb (ufbx import → bpy rebuild → DRACO export)
       │     └─ .glb/.gltf → process_glb_gltf (import → DRACO re-export)
       └─ ext in CAD → convert_cad()                     # FreeCAD GUI macro
             └─ then apply_draco_compression(output.glb) # re-import + DRACO re-export
```

## Working directory matters (why `cd /app/converter`)

- `main.py` sets `OUTPUT_PATH = os.path.abspath("output.glb")` → output lands in CWD.
- CAD: `convert_cad_formats.py` registers the macro via
  `os.path.abspath("freecad_converter.py")`. That file only exists in
  `/app/converter`, so **CAD conversion breaks if CWD isn't `/app/converter`**.
- FBX: `load_and_export_fbx` does its own `os.chdir(script_dir)` (the converter
  dir) before dumping temp textures, so FBX self-corrects regardless.
- Warnings JSONs are written via `os.path.abspath(...)` → also CWD.

Safest rule: run everything from `/app/converter` and read `output.glb` /
`*_errors.json` from there.

## Interpreter / env facts

- Python: `/app/converter/venv/bin/python3.11` (Python 3.11.15).
- `bpy`: Blender **5.0.0 Alpha** built into the venv from a wheel.
- `FreeCAD`: **1.0.0**, installed to `/usr/local/lib` (`FreeCAD.so`,
  `FreeCADGui.so`). It is NOT pip-installed in the venv; `utils.py` does
  `sys.path.append("/usr/local/lib")` so the venv python can import it. So a
  single python invocation handles both CAD and non-CAD — no second interpreter.
- `gc.disable()` + `faulthandler.enable()` are set in `main.py`.

## Thumbnail rendering (we drive this; not the friend's code)

`tasks.py`'s `generate_thumbnail_task` reuses this image to render a PNG preview
of the converted GLB via `app/worker/thumbnail.py` (copied into the container at
`/tmp/thumbnail.py`, run with the same venv python). Hard-won facts:

- **Use Cycles on CPU, not EEVEE/Workbench.** The Dockerfile installs Xvfb +
  X11/EGL *dev* libs but **no mesa software-GL driver** (`libgl1-mesa-dri` /
  llvmpipe). EEVEE and Workbench need a live GL context and can't be trusted on
  this GPU-less box; Cycles' CPU path tracer needs no GL at all. Conversion
  "works" only because GLTF import/export is pure data — it never renders, so a
  working converter does NOT imply a working GL stack.
- Verified end-to-end in the original `youndria/arpatent:1.5` container: a 512² /
  32-sample denoised Cycles-CPU render of a real DRACO GLB takes ~4s and comes
  out correctly framed with textures and a transparent background.
- `bpy.ops.import_scene.gltf(...)` and `bpy.ops.wm.read_factory_settings(
  use_empty=True)` are the same operators `convert_non_cad_formats.py` uses, so
  they're known-good on this Blender 5.0 build.

## Where the converter source lives now

A read-only snapshot of the in-image converter source (the `.py` files,
`Dockerfile`, requirements) is checked in at `app/worker/converter_src/`, pulled
from the running container. Read that instead of re-exec'ing into the container
for context. Re-pull only when the image tag is bumped.

## Gotcha: the image ENTRYPOINT is a broken red herring

The image's `ENTRYPOINT` is `["xvfb-run","-a","/venv/bin/python3.11","test.py"]`,
but `/venv` does not exist (the venv is at `/app/converter/venv`). That entrypoint
is only the maintainer's internal test harness (`test.py` walks `test_models/`)
and is irrelevant to us — we override it (`--entrypoint bash`) and call `main.py`
with the explicit venv path. Don't copy `/venv/...` from the entrypoint.

## Warning extraction internals (for parsing `*_errors.json`)

`handlers.py` regex-scans captured bpy log output and emits a list of
`{"message": <Turkish text>, "details": <regex group>}`. `tasks.py` then tags
each with a `phase` (`import` / `export`). Files are only written when there is
at least one match, so "file absent" == "no warnings".
