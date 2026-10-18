# Out-of-tree patches

This directory holds modifications to third-party sources that live under
`.research/` (which is gitignored). The patch files here are version-controlled
so every edit is traceable and re-applicable.

## hunyuan3d-api-server.patch

Upstream: [Tencent-Hunyuan/Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)
Base commit: `f8db63096c8282cb27354314d896feba5ba6ff8a` (at time of writing)
Target file: `api_server.py`

### What it changes

1. **`--subfolder` CLI flag** (default preserved: `hunyuan3d-dit-v2-mini-turbo`).
   Lets you select the model subfolder at launch time (e.g.
   `hunyuan3d-dit-v2-mv` for multi-view). Previously the subfolder was
   hardcoded in `ModelWorker.__init__` with no CLI override — any non-default
   model required editing the source.

2. **`--disable_flashvdm` CLI flag** (default: FlashVDM on, same as upstream).
   `pipeline.enable_flashvdm(mc_algo='mc')` was unconditional. The flag lets
   you turn it off without editing source if a model variant is incompatible.

3. **Multi-view payload support** in `/generate` and `/send`.

   Upstream only accepted `{"image": "<base64>"}`. Patched handler also accepts
   `{"images": {"front": "<b64>", "left": "<b64>", "back": "<b64>", ...}}`
   and passes the PIL dict through to the mv pipeline
   (`Hunyuan3DDiTFlowMatchingPipeline.__call__` already takes
   `Union[str, List[str], Image.Image, dict, List[dict]]` — see
   `hy3dgen/shapegen/pipelines.py:685`).

   Each view goes through `BackgroundRemover()` individually.
   Single-image payload `{"image": b64}` still works — backward compatible.

4. **Texture uses the front view** when multi-view. Upstream called
   `self.pipeline_tex(mesh, image)` where `image` was the (singular) scalar
   variable. With a dict we pick `images["front"]` (falling back to the first
   provided view) — matches the convention in
   `examples/textured_shape_gen_multiview.py:42`.

### What it does NOT change

- No new endpoints (`/generate`, `/send`, `/status/{uid}` unchanged).
- Error semantics unchanged (failures still return HTTP 404 with
  `{"text": "...", "error_code": 1}` — yes, 404; that's upstream).
- The unused `model_semaphore` is left as-is. Concurrency is enforced in the
  caller (Celery worker `--concurrency=1` on the generate queue).

### Applying on the server

```bash
# Assumes clean tree at the base commit. Verify first:
cd ~/Hunyuan3D-2
git fetch origin && git checkout f8db63096c8282cb27354314d896feba5ba6ff8a

# Apply:
git apply --check /path/to/ARDesign/patches/hunyuan3d-api-server.patch
git apply /path/to/ARDesign/patches/hunyuan3d-api-server.patch
```

Or use the wrapper: `bash patches/apply.sh /path/to/Hunyuan3D-2`.

### Launching the patched server

For the multi-view + textured config the friend converged on:

```bash
conda activate hunyuan3d
cd ~/Hunyuan3D-2
python3 api_server.py \
  --host 127.0.0.1 \
  --port 8081 \
  --model_path tencent/Hunyuan3D-2mv \
  --subfolder hunyuan3d-dit-v2-mv \
  --tex_model_path tencent/Hunyuan3D-2 \
  --enable_tex
```

Binds to loopback only so it's not publicly reachable — our Celery worker
(in Docker) hits it via `host.docker.internal:8081` with
`extra_hosts: "host.docker.internal:host-gateway"`.

### Regenerating after edits

If you edit `.research/Hunyuan3D-2/api_server.py` locally:

```bash
cd .research/Hunyuan3D-2
git diff api_server.py > ../../patches/hunyuan3d-api-server.patch
```

Update the base commit SHA in this README if upstream has moved.

### If upstream changes the file

`git apply` will refuse with a conflict. Options:
1. Rebase the patch manually against the new upstream (re-apply each hunk).
2. Re-clone, re-do the edits on top of the new HEAD, regenerate the diff.

The patch is intentionally small (38+/15-) to make rebases cheap.