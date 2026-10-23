# Converter measurement run

`measurement.pdf` specifies 14 representative inputs: two each of OBJ, STL,
GLB/glTF, and FBX; three CAD inputs (two STEP and one IGES); and three malformed
inputs. Within each valid format group, include a small and a large model. Include
at least one millimeter source and one inch source. Keep one model per source file.

## Prepare inputs

Put the 14 model files in one directory. Keep companion files beside their model;
the runner stages those files together (for example, an OBJ's MTL and textures).
For each model, an optional same-stem JSON sidecar sets its source unit and group:

```json
{"unit":"mm", "group":"OBJ", "expected_failure":false}
```

Units are `mm`, `cm`, `in`, or `m`; omitted units default to meters. Set
`expected_failure` to `true` for the three deliberately malformed inputs. Group
names in the report are `OBJ`, `STL`, `GLB/glTF`, `FBX`, and `CAD`.

## Run

Run from `fastapi_app/` on a machine with Docker CLI access to the daemon and the
configured converter image pulled:

```powershell
python scripts/measure_converter.py C:\path\to\measurement-inputs `
  --image ismayilovh/ardesign-converter:latest `
  --output measurement-results `
  --csv measurement-results\measurement.csv
```

`CONVERTER_IMAGE` can select the same pinned image used by the server. Container
CPU and memory limits default to 1.5 CPUs and 12 GiB, matching the worker. Each
input is run in a fresh, network-isolated container. The timer wraps only the
converter process; it excludes Celery queue wait, container startup, input
staging, and the two post-conversion GLB exports. Malformed files are retained as rows
with their error and any converter warnings.

## Read the results

The CSV records the converted output's triangle count, converter status and
messages, duration, Draco and non-Draco GLB sizes, compression reduction, and
output bounds. It also includes columns for source bounds, maximum bounds
difference, and mean/maximum surface deviation. Complete those fields using the
PDF's Blender alignment/unit procedure and its supplied trimesh distance script.
The runner saves the two GLBs under `measurement-results/<model>/` for this
comparison. Record system CPU/RAM, Blender and FreeCAD versions, and Draco
quantization in the accompanying report; the image contract documents its
configured Draco level/quantization, but verify the actual tested image tag.
Generate the report table and malformed-input notes with:

```powershell
python scripts/summarize_measurement.py measurement-results\measurement.csv `
  --output measurement-results\measurement-summary.md
```

After entering the manual deviation values into the CSV, rerun the summary
command to refresh the group and total aggregates. Add the requested side-by-side
source/output screenshot and record the measurement date in the final report.

**Draco comparison limitation:** the configured external converter exposes no
Draco-off option to this server. Therefore, the runner converts each source
once, then re-exports that converted mesh through Blender with Draco enabled and
disabled. This provides comparable compressed/uncompressed sizes for identical
geometry, but it does not measure a second end-to-end converter run with Draco
disabled or compare geometry loss introduced by Draco. Those claims require a
converter image that supports disabling Draco during its conversion pipeline.
The output bounds and triangle count describe the converted mesh; source bounds
and deviation must be measured against the original source/reference as the PDF
specifies. For malformed FBX files that warn but still produce output, review
the message and classify them as warning-success rather than successful cleanly.
