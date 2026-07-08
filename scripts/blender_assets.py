from __future__ import annotations

import argparse
import glob
import json
import math
import random
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    blender_separator = argv.index("--") if "--" in argv else len(argv)
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--action", choices=["check", "append-smoke"], required=True)
    parser.add_argument("--allow-blendkit-fallback", action="store_true")
    parser.add_argument("--output-blend")
    return parser.parse_args(argv[blender_separator + 1 :])


def read_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_candidate(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path


def find_local_asset(project_root: Path, asset: dict) -> Path | None:
    for raw_path in asset.get("local_paths", []):
        path = resolve_candidate(project_root, raw_path)
        if path.is_file():
            return path

    for raw_glob in asset.get("cache_globs", []):
        pattern = str(resolve_candidate(project_root, raw_glob))
        matches = sorted(Path(match) for match in glob.glob(pattern) if Path(match).is_file())
        if matches:
            return matches[0]
    return None


def append_material(file_path: Path, material_name: str):
    before = set(bpy.data.materials)
    with bpy.data.libraries.load(str(file_path), link=False, relative=False) as (
        data_from,
        data_to,
    ):
        if material_name in data_from.materials:
            data_to.materials = [material_name]
        elif data_from.materials:
            data_to.materials = [data_from.materials[0]]
        else:
            raise RuntimeError(f"No materials found in {file_path}")

    appended = [material for material in bpy.data.materials if material not in before]
    return appended[0] if appended else bpy.data.materials.get(material_name)


def append_collection(file_path: Path, collection_name: str):
    before = set(bpy.data.collections)
    with bpy.data.libraries.load(str(file_path), link=False, relative=False) as (
        data_from,
        data_to,
    ):
        if collection_name in data_from.collections:
            data_to.collections = [collection_name]
        elif data_from.collections:
            data_to.collections = [data_from.collections[0]]
        else:
            raise RuntimeError(f"No collections found in {file_path}")

    appended = [collection for collection in bpy.data.collections if collection not in before]
    collection = appended[0] if appended else bpy.data.collections.get(collection_name)
    if collection is None:
        raise RuntimeError(f"Collection {collection_name!r} was not appended from {file_path}")
    if collection.name not in bpy.context.scene.collection.children.keys():
        bpy.context.scene.collection.children.link(collection)
    return collection


def jittered_transform(transform: dict, jitter: dict, rng: random.Random | None) -> dict:
    if rng is None or not jitter:
        return transform

    updated = dict(transform)
    if "location" in transform:
        sigmas = jitter.get("location_sigma", [0.0, 0.0, 0.0])
        updated["location"] = [
            value + rng.gauss(0.0, sigmas[index]) for index, value in enumerate(transform["location"])
        ]
    if "rotation_degrees" in transform:
        sigmas = jitter.get("rotation_degrees_sigma", [0.0, 0.0, 0.0])
        updated["rotation_degrees"] = [
            value + rng.gauss(0.0, sigmas[index])
            for index, value in enumerate(transform["rotation_degrees"])
        ]
    return updated


def set_transform(obj, transform: dict) -> None:
    if not obj or not transform:
        return
    if "location" in transform:
        obj.location = transform["location"]
    if "rotation_degrees" in transform:
        obj.rotation_euler = [math.radians(value) for value in transform["rotation_degrees"]]
    if "scale" in transform:
        obj.scale = transform["scale"]


def append_local_asset(
    asset_key: str,
    asset: dict,
    file_path: Path,
    rng: random.Random | None = None,
):
    kind = asset["kind"]
    datablock = asset["datablock"]
    if kind == "material":
        material = append_material(file_path, datablock)
        if material is None:
            raise RuntimeError(f"Material {datablock!r} could not be loaded for {asset_key}")
        print(f"{asset_key}: loaded material {material.name} from {file_path}")
        return material

    if kind == "collection":
        collection = append_collection(file_path, datablock)
        root_name = asset.get("root_object")
        root_object = bpy.data.objects.get(root_name) if root_name else None
        transform = jittered_transform(asset.get("transform", {}), asset.get("jitter", {}), rng)
        set_transform(root_object, transform)
        print(f"{asset_key}: loaded collection {collection.name} from {file_path}")
        return collection

    raise ValueError(f"{asset_key}: unsupported asset kind {kind!r}")


def blenderkit_fallback(asset_key: str, asset: dict):
    blendkit = asset.get("blendkit") or {}
    asset_base_id = blendkit.get("asset_base_id")
    if not asset_base_id:
        raise RuntimeError(f"{asset_key}: no local asset and no BlendKit asset_base_id")

    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.user_default.blenderkit")
    except Exception as exc:
        raise RuntimeError(f"{asset_key}: could not enable BlenderKit fallback: {exc}") from exc

    try:
        result = bpy.ops.scene.blenderkit_download(asset_base_id=asset_base_id)
    except Exception as exc:
        raise RuntimeError(f"{asset_key}: BlendKit fallback failed for {asset_base_id}: {exc}") from exc

    print(f"{asset_key}: requested BlendKit fallback asset_base_id={asset_base_id}: {result}")
    return result


def resolve_or_fallback(project_root: Path, asset_key: str, asset: dict, allow_fallback: bool):
    file_path = find_local_asset(project_root, asset)
    if file_path:
        return file_path
    if allow_fallback:
        return None
    raise RuntimeError(
        f"{asset_key}: no local/cached .blend found; rerun with BlendKit fallback enabled "
        "or download/cache this asset first"
    )


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def main() -> int:
    args = parse_args()
    manifest = read_manifest(Path(args.manifest_json))
    project_root = Path(manifest["project_root"])
    assets = manifest["assets"]

    if args.action == "append-smoke":
        reset_scene()

    failures = []
    for asset_key, asset in assets.items():
        try:
            local_path = resolve_or_fallback(
                project_root, asset_key, asset, args.allow_blendkit_fallback
            )
            if local_path:
                if args.action == "append-smoke":
                    append_local_asset(asset_key, asset, local_path)
                else:
                    print(f"{asset_key}: local/cached {local_path}")
            elif args.allow_blendkit_fallback:
                if args.action == "append-smoke":
                    blenderkit_fallback(asset_key, asset)
                else:
                    print(
                        f"{asset_key}: no local/cached file; BlendKit fallback "
                        f"{asset.get('blendkit', {}).get('asset_base_id')}"
                    )
        except Exception as exc:
            failures.append(str(exc))

    if args.action == "append-smoke" and args.output_blend:
        bpy.ops.wm.save_as_mainfile(filepath=args.output_blend)

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
