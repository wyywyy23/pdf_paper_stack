"""Frozen-scene paper-material comparison; run with Blender --python ... -- --help."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_state(scene):
    """Assert geometry, transforms, lights and camera are unchanged between samples."""
    graph = bpy.context.evaluated_depsgraph_get()
    rows = []
    for obj in scene.objects:
        row = [obj.name, obj.type, [list(r) for r in obj.matrix_world]]
        if obj.type == "MESH":
            evaluated = obj.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                row.append([list(v.co) for v in mesh.vertices])
            finally:
                evaluated.to_mesh_clear()
        elif obj.type == "LIGHT":
            row.append([obj.data.type, obj.data.energy, list(obj.data.color),
                        getattr(obj.data, "spot_size", None), getattr(obj.data, "shadow_soft_size", None)])
        elif obj.type == "CAMERA":
            focus = obj.data.dof.focus_object
            row.append([obj.data.lens, obj.data.dof.focus_distance, obj.data.dof.aperture_fstop,
                        list(focus.location) if focus else None])
        rows.append(row)
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--distances", default="0,0.25,0.5,1")
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--resolution", default="960x540")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Use a fresh output directory to preserve earlier comparisons")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.scene.resolve()))
    scene = bpy.context.scene
    cover = next(o for o in scene.objects if o.get("paper_stack_layout") == "stack" and o.get("paper_index") == 0)
    material = cover.data.materials[0].copy()
    cover.data.materials[0] = material
    noise = next(n for n in material.node_tree.nodes if n.label == "Shared paper surface")
    bump = next(link.to_node for link in noise.outputs["Fac"].links if link.to_node.type == "BUMP")
    scene.cycles.seed = 0
    scene.cycles.use_animated_seed = False
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = map(int, args.resolution.split("x"))
    scene.render.resolution_percentage = 100
    baseline = frozen_state(scene)
    manifest = {"scene_sha256": digest(args.scene), "fixed_geometry_camera_lights_sha256": baseline,
                "samples": args.samples, "render_seed": 0, "resolution": args.resolution,
                "denoise": True, "view_transform": scene.view_settings.view_transform,
                "look": scene.view_settings.look, "exposure": scene.view_settings.exposure,
                "strength": bump.inputs["Strength"].default_value,
                "noise_dimensions": noise.noise_dimensions, "stages": []}
    for distance in map(float, args.distances.split(",")):
        if not 0 <= distance <= 10:
            raise ValueError("Distances must be finite and between 0 and 10")
        bump.inputs["Distance"].default_value = distance
        if frozen_state(scene) != baseline:
            raise AssertionError("A frozen scene input changed during comparison")
        name = "distance_" + str(distance).replace(".", "p") + ".png"
        scene.render.filepath = str((args.output_dir / name).resolve())
        bpy.ops.render.render(write_still=True)
        manifest["stages"].append({"only_changed_input": "cover macro Distance", "distance": distance,
                                   "file": name, "sha256": digest(scene.render.filepath)})
        (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
