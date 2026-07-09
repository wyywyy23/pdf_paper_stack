from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import blender_assets


def blender_argv(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return []


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a PDF paper stack Blender scene.")
    parser.add_argument("--scene-json", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--allow-blendkit-fallback", action="store_true")
    return parser.parse_args(argv)


def read_scene_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def natural_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name)]


def page_images(image_dir: Path) -> list[Path]:
    images = [
        path
        for path in image_dir.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    return sorted(images, key=natural_key)


def as_radians(values: list[float]) -> list[float]:
    return [math.radians(value) for value in values]


def set_transform(obj: Any, transform: dict[str, Any]) -> None:
    if "location" in transform:
        obj.location = transform["location"]
    if "rotation_degrees" in transform:
        obj.rotation_euler = as_radians(transform["rotation_degrees"])
    if "scale" in transform:
        obj.scale = transform["scale"]


def set_bsdf_value(bsdf: Any, names: list[str], value: float) -> None:
    for name in names:
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = value
            return
    print(f"Skipping missing BSDF input aliases: {names}")


def add_noise_bump(material: Any, bump_config: dict[str, Any], bsdf: Any) -> Any | None:
    if not bump_config.get("enabled", False):
        return None

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    noise = nodes.new(type="ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = bump_config.get("scale", 1000)
    noise.inputs["Detail"].default_value = bump_config.get("detail", 16)
    noise.inputs["Roughness"].default_value = bump_config.get("roughness", 0.5)

    bump = nodes.new(type="ShaderNodeBump")
    bump.inputs["Strength"].default_value = bump_config.get("strength", 0.1)
    bump.inputs["Distance"].default_value = bump_config.get("distance", 1.0)
    bump.inputs["Filter Width"].default_value = bump_config.get("filter_width", 1.0)
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    return bump


def configure_page_material(obj: Any, material_config: dict[str, Any]) -> None:
    if not obj.data.materials:
        return

    material = obj.data.materials[0]
    material.use_nodes = True
    if "blend_method" in material_config:
        material.blend_method = material_config["blend_method"]
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return

    set_bsdf_value(bsdf, ["Roughness"], material_config.get("roughness", 1.0))
    set_bsdf_value(
        bsdf,
        ["Specular IOR Level", "Specular"],
        material_config.get("specular", 0.0),
    )
    set_bsdf_value(
        bsdf,
        ["Transmission Weight", "Transmission"],
        material_config.get("transmission", 0.0),
    )

    bump = add_noise_bump(material, material_config.get("bump", {}), bsdf)
    macro_bump = add_noise_bump(material, material_config.get("macro_bump", {}), bsdf)
    links = material.node_tree.links

    if bump and macro_bump:
        # Color add matches the original hand-tuned paper grain from the wood branch.
        combine_bump = material.node_tree.nodes.new(type="ShaderNodeMixRGB")
        combine_bump.blend_type = "ADD"
        combine_bump.inputs["Fac"].default_value = 1.0
        links.new(bump.outputs["Normal"], combine_bump.inputs[1])
        links.new(macro_bump.outputs["Normal"], combine_bump.inputs[2])
        links.new(combine_bump.outputs["Color"], bsdf.inputs["Normal"])
    elif bump:
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    elif macro_bump:
        links.new(macro_bump.outputs["Normal"], bsdf.inputs["Normal"])


def import_page_plane(image_path: Path) -> Any:
    bpy.ops.image.import_as_mesh_planes(
        files=[{"name": image_path.name}],
        directory=str(image_path.parent),
    )
    return bpy.context.selected_objects[0]


def build_stack(image_dir: Path, stack_config: dict[str, Any], rng: random.Random) -> float:
    images = page_images(image_dir)
    if not images:
        raise FileNotFoundError(f"No page images found in {image_dir}")

    z_offset = stack_config.get("z_offset", 0.0005)
    z_position = 0.0
    degree_rotate_max = stack_config.get("degree_rotate_max", 1.5)
    reference_pages = stack_config.get("spread_reference_pages", 8)
    degree_rotate = max(degree_rotate_max / len(images) * reference_pages, degree_rotate_max)
    rotation_sign = stack_config.get("rotation_sign", 1.0)
    material_config = stack_config.get("material", {})

    for index, image_path in enumerate(images):
        obj = import_page_plane(image_path)
        obj.location.z = z_position
        z_position -= z_offset
        configure_page_material(obj, material_config)

        obj.location.y = obj.dimensions.y * stack_config.get("y_offset_factor", 2.0)
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY")
        bpy.ops.transform.rotate(
            value=math.radians(
                rotation_sign
                * rng.gauss(0.0, stack_config.get("page_center_rotation_sigma", 1.0))
            ),
            orient_axis="Z",
        )
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        bpy.ops.transform.rotate(
            value=math.radians(
                rotation_sign
                * (
                    -degree_rotate * index
                    + rng.gauss(0.0, stack_config.get("fan_rotation_sigma", 0.2))
                )
            ),
            orient_axis="Z",
        )

    return z_position


def configure_render(render_config: dict[str, Any]) -> None:
    scene = bpy.context.scene
    scene.render.engine = render_config.get("engine", "CYCLES")
    if scene.render.engine == "CYCLES":
        scene.cycles.device = render_config.get("device", "GPU")
        scene.cycles.samples = render_config.get("samples", 1024)
        scene.cycles.use_denoising = render_config.get("denoise", False)

    resolution = render_config.get("resolution", [1920, 1080])
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.film_transparent = render_config.get("film_transparent", True)

    view_transform = render_config.get("view_transform")
    look = render_config.get("look")
    if view_transform:
        scene.view_settings.view_transform = view_transform
    if look:
        scene.view_settings.look = look


def load_configured_assets(
    project_root: Path,
    assets: dict[str, Any],
    asset_keys: list[str],
    allow_blendkit_fallback: bool,
    rng: random.Random,
    transform_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    loaded = {}
    for key in asset_keys:
        asset = assets[key]
        local_path = blender_assets.resolve_or_fallback(
            project_root, key, asset, allow_blendkit_fallback
        )
        if local_path:
            loaded[key] = blender_assets.append_local_asset(
                key,
                asset,
                local_path,
                rng=rng,
                transform_context=transform_context,
            )
        elif allow_blendkit_fallback:
            loaded[key] = blender_assets.blenderkit_fallback(key, asset)
    return loaded


def add_background(
    z_position: float,
    background_config: dict[str, Any],
    loaded_assets: dict[str, Any],
) -> Any:
    z_gap = background_config.get("z_gap", 0.0005)
    bpy.ops.mesh.primitive_plane_add(
        size=background_config.get("size", 10),
        location=(0, 0, z_position - z_gap),
    )
    plane = bpy.context.object
    plane.name = background_config.get("name", "BackgroundPlane")

    material_key = background_config.get("material_asset")
    material = loaded_assets.get(material_key) if material_key else None
    if material and hasattr(plane.data, "materials"):
        plane.data.materials.append(material)
    configure_background_uv(plane, background_config.get("uv_map", {}))
    return plane


def configure_background_uv(plane: Any, uv_config: dict[str, Any]) -> None:
    if not uv_config:
        return

    coordinates = uv_config.get("coordinates")
    if not coordinates:
        return

    uv_name = uv_config.get("name", "automap")
    uv_layer = plane.data.uv_layers.get(uv_name) or plane.data.uv_layers.new(name=uv_name)
    for loop_data, coordinate in zip(uv_layer.data, coordinates):
        loop_data.uv = coordinate

    if uv_config.get("active", True):
        plane.data.uv_layers.active = uv_layer
    if uv_config.get("active_render", True):
        for layer in plane.data.uv_layers:
            layer.active_render = layer == uv_layer


def add_lights(lights: list[dict[str, Any]]) -> None:
    for light_config in lights:
        if light_config.get("enabled", True) is False:
            continue

        light_type = light_config.get("type", "POINT")
        bpy.ops.object.light_add(
            type=light_type,
            location=light_config.get("location", [0, 0, 0]),
        )
        light = bpy.context.object
        light.name = light_config.get("name", light.name)
        set_transform(light, light_config)

        light.data.energy = light_config.get("energy", light.data.energy)
        if "color" in light_config:
            light.data.color = light_config["color"]
        if light_type == "SPOT":
            if "spot_size_degrees" in light_config:
                light.data.spot_size = math.radians(light_config["spot_size_degrees"])
            if "spot_blend" in light_config:
                light.data.spot_blend = light_config["spot_blend"]


def add_camera(camera_config: dict[str, Any]) -> Any:
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = camera_config.get("name", "Camera")
    set_transform(camera, camera_config)
    camera.data.lens = camera_config.get("lens", camera.data.lens)

    dof = camera_config.get("dof", {})
    camera.data.dof.use_dof = dof.get("enabled", False)
    if "focus_distance" in dof:
        camera.data.dof.focus_distance = dof["focus_distance"]
    if "fstop" in dof:
        camera.data.dof.aperture_fstop = dof["fstop"]

    bpy.context.scene.camera = camera
    return camera


def rng_from_config(config: dict[str, Any], key: str = "seed") -> random.Random:
    if key in config:
        return random.Random(config[key])
    if "seed" in config:
        return random.Random(config["seed"])
    seeds = config.get("seeds", [])
    if not seeds:
        return random.Random()
    chooser = random.Random(sum(int(seed) for seed in seeds))
    return random.Random(chooser.choice(seeds))


def build_scene(args: argparse.Namespace) -> None:
    config = read_scene_config(args.scene_json)
    project_root = Path(config["project_root"])
    paper = config["paper"]
    scene_config = config["scene"]
    random_config = config.get("random", {})
    stack_rng = rng_from_config(random_config, "stack_seed")
    asset_rng = rng_from_config(random_config, "asset_seed")

    output_blend = args.output or Path(paper["blend"])
    output_blend = Path(output_blend).resolve()

    clear_scene()
    configure_render(scene_config.get("render", {}))

    z_position = build_stack(Path(paper["images"]), scene_config.get("stack", {}), stack_rng)
    background_config = scene_config.get("background", {})
    table_z = z_position - background_config.get("z_gap", 0.0005)
    transform_context = {
        "z_references": {
            "stack_top": 0.0,
            "table": table_z,
            "background": table_z,
        }
    }
    asset_keys = scene_config.get("assets", {}).get("load", [])
    loaded_assets = load_configured_assets(
        project_root,
        config["assets"],
        asset_keys,
        args.allow_blendkit_fallback,
        asset_rng,
        transform_context,
    )
    add_background(z_position, background_config, loaded_assets)
    add_lights(scene_config.get("lights", []))
    add_camera(scene_config.get("camera", {}))

    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    print(f"Saved Blender scene: {output_blend}")


def main() -> None:
    args = parse_args(blender_argv(sys.argv))
    build_scene(args)


if __name__ == "__main__":
    main()
