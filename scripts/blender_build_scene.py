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
from mathutils import Vector

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
    generated = [path for path in images if re.fullmatch(r"page_[0-9]+\.(?:jpg|jpeg|png)", path.name, re.IGNORECASE)]
    return sorted(generated or images, key=natural_key)


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
    noise.label = bump_config.get("label", "")
    if "seed" in bump_config:
        noise.noise_dimensions = "4D"
        noise.inputs["W"].default_value = bump_config["seed"]
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

    if bump and macro_bump and material_config.get("normal_blend") == "layered":
        # Feed the broad paper normal into the fine grain, rather than adding
        # two normal vectors as RGB colors (which biases the surface normal).
        links.new(macro_bump.outputs["Normal"], bump.inputs["Normal"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    elif bump and macro_bump:
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


def curve_compact_page(obj: Any, page_height: float, center_y: float, amplitude: float, depth: float) -> None:
    """A shared, shallow edge curl lets adjoining sheets conform without crossing."""
    if amplitude == 0:
        return
    old = obj.data
    width = max(v.co.x for v in old.vertices) - min(v.co.x for v in old.vertices)
    height = max(v.co.y for v in old.vertices) - min(v.co.y for v in old.vertices)
    uv_name = old.uv_layers.active.name if old.uv_layers.active else "UVMap"
    # Preserve the imported image's UV orientation rather than assuming its axes.
    corners = {}
    if old.uv_layers.active:
        for loop in old.loops:
            co = old.vertices[loop.vertex_index].co
            corners[(int(co.x > 0), int(co.y > 0))] = old.uv_layers.active.data[loop.index].uv.copy()
    def smooth(value):
        t = max(0.0, min(1.0, value))
        return t*t*(3-2*t)
    vertices, faces, uvs = [], [], []
    nx, ny = 16, 24
    angle = obj.rotation_euler.z
    cosine, sine = math.cos(angle), math.sin(angle)
    for row in range(ny+1):
        v = row / ny
        for col in range(nx+1):
            u = col / nx
            x, y = (u-.5)*width, (v-.5)*height
            # Evaluate one world-space support surface for every layer. The
            # amplitude decreases monotonically to a flat bottom sheet.
            wx = obj.location.x + cosine*x - sine*y
            wy = obj.location.y + sine*x + cosine*y - center_y
            xn, yn = wx/(width*.5), wy/(page_height*.5)
            front = smooth((-yn-.55)/.45)
            right = smooth((xn-.55)/.45)
            back = smooth((yn-.55)/.45)
            bend = front*(.25+.75*max(0,min(1,(xn+1)/2))**2) + .35*right*back
            vertices.append((x,y,amplitude*page_height*depth*bend))
            if len(corners) == 4:
                uv = sum((corners[(a,b)]*((u if a else 1-u)*(v if b else 1-v)) for a,b in corners), Vector((0,0)))
                uvs.append(tuple(uv))
            else:
                uvs.append((u,v))
    for row in range(ny):
        for col in range(nx):
            a = row*(nx+1)+col
            faces.append((a,a+1,a+nx+2,a+nx+1))
    mesh = bpy.data.meshes.new(old.name + " curved")
    mesh.from_pydata(vertices,[],faces)
    mesh.update()
    for material in old.materials:
        mesh.materials.append(material)
    uv_layer = mesh.uv_layers.new(name=uv_name)
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uvs[loop.vertex_index]
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj.data = mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)


def build_compact_stack(images: list[Path], stack_config: dict[str, Any], rng: random.Random) -> float:
    """A nearly aligned pile with real paper edges and height proportional to page count."""
    compact = stack_config.get("compact", {})
    values = {"page_thickness": 0.0012, "page_gap": 0.00008,
              "rotation_sigma": 0.10, "rotation_limit": 0.25,
              "position_sigma": 0.0005, "position_limit": 0.0015,
              "outlier_fraction": 0.08, "outlier_distance": 0.008, "outlier_rotation": 0.18,
              "edge_curl": 0.0035, "paper_grain_distance": 0.00015,
              "paper_surface_scale": 1.5, "paper_surface_strength": 0.5, "paper_surface_distance": 0.5,
              "paper_surface_seed": 0.0, "paper_surface_falloff": 1.0}
    for key, default in values.items():
        value = float(compact.get(key, default))
        if not math.isfinite(value) or value < 0 or (key == "page_thickness" and value == 0):
            raise ValueError(f"Invalid compact-stack parameter: {key}")
        values[key] = value
    if values["paper_surface_falloff"] <= 0:
        raise ValueError("paper_surface_falloff must be positive")
    if values["outlier_fraction"] > 1:
        raise ValueError("outlier_fraction must be between 0 and 1")
    count = min(len(images) - 1, max(1, round((len(images) - 1) * values["outlier_fraction"]))) if values["outlier_fraction"] and len(images) > 2 else 0
    # Correlated local groups reproduce the gently uneven contour seen in
    # reference photos; isolated full-sheet kicks produce artificial shelves.
    outlier_rng = random.Random()
    if count:
        outlier_rng.setstate(rng.getstate())
    centers = outlier_rng.sample(range(1, len(images)), count) if count else []
    groups = [(center, outlier_rng.uniform(1.8, 3.5), outlier_rng.uniform(0, 2*math.pi),
               outlier_rng.uniform(.6, 1.0), outlier_rng.uniform(-1, 1)) for center in centers]
    edge = bpy.data.materials.new("Paper stack edges")
    edge.use_nodes = True
    bsdf = edge.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.82, 0.81, 0.77, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.95
    set_bsdf_value(bsdf, ["Specular IOR Level", "Specular"], 0.12)
    reference_height = None
    reference_width = None
    bottom_z = 0.0
    for index, image_path in enumerate(images):
        obj = import_page_plane(image_path)
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY")
        if reference_height is None:
            reference_height = obj.dimensions.y
            reference_width = obj.dimensions.x
            if reference_height <= 0 or reference_width <= 0:
                raise ValueError("Page dimensions must be positive")
        surface_depth = (len(images)-1-index)/(len(images)-1) if len(images)>1 else 1.0
        surface_amplitude = surface_depth**values["paper_surface_falloff"]
        obj["paper_surface_amplitude"] = surface_amplitude
        material_config = dict(stack_config.get("material", {}))
        # Keep silhouette/curl and surface shading independently adjustable.
        # Fixing large wrinkles must preserve gentle paper-surface modulation.
        # A common planar frame avoids amplification by Generated Z normalization.
        material_config["normal_blend"] = "layered"
        material_config["macro_bump"] = {
            "enabled": surface_amplitude > 0,
            "label": "Shared paper surface",
            "scale": values["paper_surface_scale"], "detail": 0.5, "roughness": 0.5,
            "strength": values["paper_surface_strength"],
            "distance": values["paper_surface_distance"] * surface_amplitude,
            "filter_width": 1.0,
        }
        material_config["bump"] = {**material_config.get("bump", {}), "distance": values["paper_grain_distance"], "strength": 0.10}
        configure_page_material(obj, material_config)
        if obj.data.materials and obj.data.materials[0].node_tree:
            nodes = obj.data.materials[0].node_tree.nodes
            links = obj.data.materials[0].node_tree.links
            for node in list(nodes):
                if node.type != "TEX_NOISE":
                    continue
                # Calibrated by one-factor renders on a frozen scene. The old
                # flat mesh's Generated Z is measured as .5; 4D W=17 is a
                # different field, not an equivalent seed for that material.
                # Keep the shared 3D field fixed; attenuate height, not pattern.
                geometry = nodes.new(type="ShaderNodeNewGeometry")
                scale = nodes.new(type="ShaderNodeVectorMath")
                scale.operation = "MULTIPLY"
                scale.inputs[1].default_value = (1/reference_width, 1/reference_height, 0)
                offset = nodes.new(type="ShaderNodeVectorMath")
                offset.operation = "ADD"
                seed = values["paper_surface_seed"] if node.label == "Shared paper surface" else 0
                offset.inputs[1].default_value = (.5, .5-stack_config.get("y_offset_factor", 2.0), .5+seed)
                links.new(geometry.outputs["Position"], scale.inputs[0])
                links.new(scale.outputs["Vector"], offset.inputs[0])
                links.new(offset.outputs["Vector"], node.inputs["Vector"])
        thickness = values["page_thickness"] * reference_height
        gap = values["page_gap"] * reference_height
        obj.location.y = obj.dimensions.y * stack_config.get("y_offset_factor", 2.0)
        obj.location.z = -index * (thickness + gap)
        if index:
            # Bounded independent jitter; never an accumulating fan rotation.
            limit = values["position_limit"] * reference_height
            sigma = values["position_sigma"] * reference_height
            obj.location.x += max(-limit, min(limit, rng.gauss(0.0, sigma)))
            obj.location.y += max(-limit, min(limit, rng.gauss(0.0, sigma)))
            angle = max(-values["rotation_limit"], min(values["rotation_limit"], rng.gauss(0.0, values["rotation_sigma"])))
            obj.rotation_euler.z += math.radians(angle)
        if index and groups:
            dx, dy, turn, influence = 0.0, 0.0, 0.0, 0.0
            for center, width, direction, strength, rotation in groups:
                weight = math.exp(-.5*((index-center)/width)**2) * strength
                dx += math.cos(direction)*weight
                dy += math.sin(direction)*weight
                turn += rotation*weight
                influence = max(influence, weight)
            # Taper at the cover; cap overlapping groups at the same small bound.
            taper = min(1.0, index/3.0)
            length = max(1.0, math.hypot(dx,dy))
            obj.location.x += dx/length * values["outlier_distance"] * reference_height * taper
            obj.location.y += dy/length * values["outlier_distance"] * reference_height * taper
            obj.rotation_euler.z += math.radians(max(-1,min(1,turn))*values["outlier_rotation"]*taper)
            obj["paper_stack_outlier"] = influence > .35
        obj["paper_stack_group_centers"] = centers
        depth = (len(images)-1-index)/(len(images)-1) if len(images)>1 else 0.0
        curve_compact_page(obj, reference_height,
                           reference_height * stack_config.get("y_offset_factor", 2.0),
                           values["edge_curl"], depth)
        edge_index = len(obj.data.materials)
        obj.data.materials.append(edge)
        solidify = obj.modifiers.new("Paper thickness", "SOLIDIFY")
        solidify.thickness = thickness
        solidify.offset = -1.0
        solidify.use_even_offset = True
        solidify.material_offset = edge_index
        solidify.material_offset_rim = edge_index
        if values["edge_curl"]:
            rim = obj.modifiers.new("Crisp paper rim", "EDGE_SPLIT")
            rim.split_angle = math.radians(30)
            rim.use_edge_angle = True
        obj["paper_stack_layout"] = "stack"
        obj["paper_index"] = index
        bottom_z = obj.location.z - thickness
    return bottom_z


def build_stack(image_dir: Path, stack_config: dict[str, Any], rng: random.Random) -> float:
    images = page_images(image_dir)
    if not images:
        raise FileNotFoundError(f"No page images found in {image_dir}")

    layout = stack_config.get("layout", "fan")
    if layout == "stack":
        return build_compact_stack(images, stack_config, rng)
    if layout != "fan":
        raise ValueError("Page layout must be fan or stack")

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
    scene.render.resolution_percentage = 100
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


def add_lights(lights: list[dict[str, Any]], compact: dict[str, Any] | None = None) -> None:
    for light_config in lights:
        if light_config.get("enabled", True) is False:
            continue

        light_config = dict(light_config)
        styling = (compact or {}).get("lighting", {})
        if light_config.get("name") == "KeySpot" and styling:
            light_config.update(spot_size_degrees=styling.get("spot_size_degrees", 14),
                                energy=styling.get("energy", 6500))
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
            if styling:
                light.data.shadow_soft_size = float(styling.get("radius", 0.25))
    styling = (compact or {}).get("lighting", {})
    if styling.get("fill_energy", 0):
        bpy.ops.object.light_add(type="AREA", location=(-0.8, 1.2, 2.2))
        fill = bpy.context.object
        fill.name = "Stack soft fill"
        fill.data.energy = float(styling["fill_energy"])
        fill.data.shape = "DISK"
        fill.data.size = 3.0
        fill.rotation_euler = (Vector((0, 2, 0)) - fill.location).to_track_quat('-Z', 'Y').to_euler()


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


def place_stack_table_props(stack_config: dict[str, Any], definitions: dict[str, Any], loaded: dict[str, Any]) -> None:
    """Arrange table props around compact pages, using real surface bounds."""
    bpy.context.view_layer.update()
    pages = [obj for obj in bpy.context.scene.objects if obj.get("paper_stack_layout") == "stack"]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = [obj.evaluated_get(depsgraph).matrix_world @ Vector(corner)
              for obj in pages for corner in obj.evaluated_get(depsgraph).bound_box]
    if not points:
        return
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    gap = 0.03 * (max(v.co.y for v in pages[0].data.vertices) - min(v.co.y for v in pages[0].data.vertices))
    placements = stack_config.get("compact", {}).get("prop_placements", {})
    height = gap / 0.03
    for key, collection in loaded.items():
        definition = definitions[key]
        if definition.get("kind") != "collection" or definition.get("transform", {}).get("z_reference") != "table":
            continue
        root = bpy.data.objects.get(definition.get("root_object", ""))
        if root is None:
            continue
        prop_points = blender_assets.collection_world_points(collection)
        if not prop_points:
            continue
        a = Vector(tuple(min(p[i] for p in prop_points) for i in range(3)))
        b = Vector(tuple(max(p[i] for p in prop_points) for i in range(3)))
        placement = placements.get(key)
        shift = Vector((0, 0, 0))
        if placement:
            side = placement.get("side", "right")
            clearance = float(placement.get("gap", 0.04)) * height
            along = float(placement.get("along", 0)) * height
            if side not in {"above", "right", "left", "below"} or not all(math.isfinite(v) for v in (clearance, along)) or clearance < 0:
                raise ValueError(f"Invalid stack prop placement for {key}")
            if side in {"above", "below"}:
                shift.x = (low.x + high.x - a.x - b.x) / 2 + along
                shift.y = high.y + clearance - a.y if side == "above" else low.y - clearance - b.y
            else:
                shift.y = (low.y + high.y - a.y - b.y) / 2 + along
                shift.x = high.x + clearance - a.x if side == "right" else low.x - clearance - b.x
        elif all(a[i] < high[i] and b[i] > low[i] for i in range(3)):
            shift.x = high.x + gap - a.x if a.x+b.x >= low.x+high.x else low.x-gap-b.x
        matrix = root.matrix_world.copy()
        matrix.translation += shift
        root.matrix_world = matrix
        bpy.context.view_layer.update()



def focus_compact_title(camera: Any, stack_config: dict[str, Any]) -> None:
    """Focus plane passes through a configurable point on the actual cover."""
    uv = stack_config.get("compact", {}).get("focus_uv", [0.5, 0.76])
    if not isinstance(uv, (list, tuple)) or len(uv) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in uv):
        raise ValueError("compact.focus_uv must contain two normalized coordinates")
    cover = next(obj for obj in bpy.context.scene.objects if obj.get("paper_stack_layout") == "stack" and obj.get("paper_index") == 0)
    vertices = cover.data.vertices
    lo = Vector(tuple(min(v.co[i] for v in vertices) for i in range(3)))
    hi = Vector(tuple(max(v.co[i] for v in vertices) for i in range(3)))
    local_point = Vector((lo.x + uv[0]*(hi.x-lo.x), lo.y + uv[1]*(hi.y-lo.y), hi.z + 1.0))
    hit, point, _, _ = cover.ray_cast(local_point, Vector((0,0,-1)))
    if not hit:
        raise ValueError("Title focus point does not intersect the cover")
    point = cover.matrix_world @ point
    focus = bpy.data.objects.get("Article title focus")
    if focus is None:
        focus = bpy.data.objects.new("Article title focus", None)
        bpy.context.scene.collection.objects.link(focus)
    focus.location = point
    focus.empty_display_size = 0.025
    focus["cover_uv"] = list(uv)
    camera.data.dof.use_dof = True
    camera.data.dof.focus_object = focus
    outward = camera.rotation_euler.to_matrix() @ Vector((0, 0, 1))
    camera.data.dof.focus_distance = (camera.location - point).dot(outward)
    bpy.context.view_layer.update()


def frame_compact_stack(camera: Any, stack_config: dict[str, Any], loaded_assets: dict[str, Any] | None = None) -> None:
    """Fit and center pages and props while keeping the original camera azimuth."""
    compact = stack_config.get("compact", {})
    if not compact.get("frame_stack", True):
        focus_compact_title(camera, stack_config)
        return
    margin = float(compact.get("camera_margin", 1.12))
    elevation = float(compact.get("camera_elevation_degrees", 35.0))
    fstop = float(compact.get("camera_fstop", 4.0))
    if not all(math.isfinite(v) for v in (margin, elevation, fstop)) or margin < 1 or not 5 <= elevation <= 85 or fstop <= 0:
        raise ValueError("Invalid stack camera settings")
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    pages = [obj for obj in bpy.context.scene.objects if obj.get("paper_stack_layout") == "stack"]
    points = []
    for obj in pages:
        evaluated = obj.evaluated_get(depsgraph)
        points.extend(evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box)
    if not points:
        raise ValueError("Cannot frame a stack without page geometry")
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    cover_center = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, high.z))
    for asset in (loaded_assets or {}).values():
        if isinstance(asset, bpy.types.Collection):
            points.extend(blender_assets.collection_world_points(asset))
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    target = (low + high) * 0.5
    camera.rotation_euler.x = math.radians(90.0 - elevation)
    camera.rotation_euler.y = 0.0
    basis = camera.rotation_euler.to_matrix()
    right, up, outward = [basis @ Vector(axis) for axis in ((1,0,0),(0,1,0),(0,0,1))]
    # Center the projected silhouette, not the world-axis bounding box: the
    # latter wastes space above a thick pile viewed obliquely.
    target += right * ((min(p.dot(right) for p in points) + max(p.dot(right) for p in points)) / 2 - target.dot(right))
    target += up * ((min(p.dot(up) for p in points) + max(p.dot(up) for p in points)) / 2 - target.dot(up))
    frame = camera.data.view_frame(scene=bpy.context.scene)
    tan_x = max(abs(c.x / c.z) for c in frame)
    tan_y = max(abs(c.y / c.z) for c in frame)
    distance = max((p-target).dot(outward) + margin * max(abs((p-target).dot(right))/tan_x,
                   abs((p-target).dot(up))/tan_y) for p in points)
    camera.location = target + outward * max(distance, camera.data.clip_start * 2)
    camera.data.dof.focus_distance = (camera.location-cover_center).dot(outward)
    camera.data.dof.aperture_fstop = fstop
    focus_compact_title(camera, stack_config)
    bpy.context.view_layer.update()


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
    if scene_config.get("stack", {}).get("layout", "fan") == "stack":
        for key in asset_keys:
            asset = config["assets"][key]
            if asset.get("kind") == "collection":
                transform = asset.setdefault("transform", {})
                transform.setdefault("z_reference", "table")
                transform.setdefault("z_align", "bottom")
    loaded_assets = load_configured_assets(
        project_root,
        config["assets"],
        asset_keys,
        args.allow_blendkit_fallback,
        asset_rng,
        transform_context,
    )
    if scene_config.get("stack", {}).get("layout", "fan") == "stack":
        place_stack_table_props(scene_config["stack"], config["assets"], loaded_assets)
    add_background(z_position, background_config, loaded_assets)
    add_lights(scene_config.get("lights", []), scene_config["stack"].get("compact", {}) if scene_config.get("stack", {}).get("layout") == "stack" else None)
    camera = add_camera(scene_config.get("camera", {}))
    if scene_config.get("stack", {}).get("layout", "fan") == "stack":
        frame_compact_stack(camera, scene_config["stack"], loaded_assets)

    output_blend.parent.mkdir(parents=True, exist_ok=True)
    # The runner stages then moves this file; keep all texture references absolute.
    bpy.ops.file.make_paths_absolute()
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), relative_remap=False)
    print(f"Saved Blender scene: {output_blend}")


def main() -> None:
    args = parse_args(blender_argv(sys.argv))
    build_scene(args)


if __name__ == "__main__":
    main()
