"""Run inside the converter image to inspect output and export Draco variants."""
import json
import os
import sys

import bpy


def mesh_stats():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    triangles = 0
    points = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        triangles += len(mesh.loop_triangles)
        points.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        evaluated.to_mesh_clear()
    if not points:
        return triangles, None
    mins = [min(point[i] for point in points) for i in range(3)]
    maxs = [max(point[i] for point in points) for i in range(3)]
    return triangles, [maxs[i] - mins[i] for i in range(3)]


source, output_dir = sys.argv[-2:]
os.makedirs(output_dir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
triangles, bounds = mesh_stats()

variants = {}
for name, draco in (("draco", True), ("no_draco", False)):
    path = os.path.join(output_dir, name + ".glb")
    options = {"filepath": path, "export_format": "GLB",
              "export_draco_mesh_compression_enable": draco}
    if draco:
        options.update({"export_draco_mesh_compression_level": 6,
                        "export_draco_position_quantization": 16,
                        "export_draco_normal_quantization": 12,
                        "export_draco_texcoord_quantization": 20,
                        "export_draco_generic_quantization": 12})
    bpy.ops.export_scene.gltf(**options)
    variants[name] = os.path.getsize(path)

print(json.dumps({"triangles": triangles, "bounds_m": bounds,
                  "sizes_bytes": variants}))
