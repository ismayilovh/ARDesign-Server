"""Headless Blender thumbnail renderer — runs INSIDE the configured converter
container, never in the FastAPI/worker process.

`generate_thumbnail_task` copies this file into an ephemeral converter
container and runs it with the converter's bundled Python/bpy:

    xvfb-run -a /app/converter/venv/bin/python3.11 thumbnail.py <in.glb> <out.png>

It imports a GLB, frames every mesh in view, and renders a square PNG with a
transparent background. Design notes:

* Engine is **Cycles on CPU**. The converter image ships no mesa software-GL
  driver (see Dockerfile), so EEVEE/Workbench — which need a live GL context —
  can't be trusted under Xvfb. Cycles' CPU path tracer needs no GL at all, so
  it renders reliably on a GPU-less box. Samples are low + denoised because
  this is a thumbnail, not a beauty render.
* The bpy API calls mirror what convert_non_cad_formats.py already uses in this
  exact image (`import_scene.gltf`, `wm.read_factory_settings(use_empty=True)`),
  so we stay on operators known to exist in their Blender 5.0 build.
"""
import math
import sys

import bpy
from mathutils import Vector

RESOLUTION = 512
SAMPLES = 32
# Unit view direction the camera looks *from* (front-ish, slightly above and to
# the side) so flat/axis-aligned designs still read as 3D.
VIEW_DIR = Vector((0.6, -1.0, 0.5)).normalized()
# Extra breathing room around the model's bounding sphere (1.0 == tight fit).
FIT_MARGIN = 1.25


def _reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_glb(path: str) -> None:
    # Same operator the converter uses for GLB/GLTF in this image.
    bpy.ops.import_scene.gltf(filepath=path)


def _scene_bounds():
    """World-space (center, radius) enclosing every mesh, or None if empty."""
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        return None

    min_v = Vector((math.inf, math.inf, math.inf))
    max_v = Vector((-math.inf, -math.inf, -math.inf))
    for obj in meshes:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            min_v = Vector((min(a, b) for a, b in zip(min_v, world)))
            max_v = Vector((max(a, b) for a, b in zip(max_v, world)))

    center = (min_v + max_v) / 2.0
    radius = (max_v - min_v).length / 2.0
    return center, (radius or 1.0)


def _add_camera(center: Vector, radius: float):
    cam_data = bpy.data.cameras.new("ThumbCam")
    cam = bpy.data.objects.new("ThumbCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    # Distance that fits the bounding sphere within the (vertical) FOV.
    fov = 2.0 * math.atan((cam_data.sensor_width / 2.0) / cam_data.lens)
    distance = (radius / math.sin(fov / 2.0)) * FIT_MARGIN

    cam.location = center + VIEW_DIR * distance
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _add_lighting() -> None:
    scene = bpy.context.scene

    world = bpy.data.worlds.new("ThumbWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
        bg.inputs[1].default_value = 0.55  # ambient fill so nothing is pure black
    scene.world = world

    sun_data = bpy.data.lights.new("ThumbSun", type="SUN")
    sun_data.energy = 3.5
    sun = bpy.data.objects.new("ThumbSun", sun_data)
    sun.rotation_euler = (math.radians(55.0), math.radians(15.0), math.radians(40.0))
    scene.collection.objects.link(sun)


def _configure_render(out_path: str) -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True

    # AgX (the 5.0 default) crushes thumbnail colors; Standard is predictable.
    try:
        scene.view_settings.view_transform = "Standard"
    except TypeError:
        pass

    scene.render.resolution_x = RESOLUTION
    scene.render.resolution_y = RESOLUTION
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.use_file_extension = False
    scene.render.filepath = out_path


def main() -> int:
    glb_path, out_path = sys.argv[-2], sys.argv[-1]

    _reset_scene()
    _import_glb(glb_path)

    bounds = _scene_bounds()
    if bounds is None:
        print("thumbnail: GLB contains no mesh objects", file=sys.stderr)
        return 2

    center, radius = bounds
    _add_camera(center, radius)
    _add_lighting()
    _configure_render(out_path)

    bpy.ops.render.render(write_still=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
