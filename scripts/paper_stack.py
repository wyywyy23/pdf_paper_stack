from __future__ import annotations

import argparse
import copy
import hashlib
import json
import secrets
import os
import math
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pdf2image import convert_from_path
import yaml


ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str | Path) -> Path:
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_assets(path: Path) -> dict:
    data = load_yaml(path)
    if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
        raise ValueError(f"{path} must contain a top-level 'assets' mapping")
    return data


def load_pipeline(path: Path) -> dict:
    data = load_yaml(path)
    papers = data.get("papers")
    if not isinstance(papers, dict):
        raise ValueError(f"{path} must contain a top-level 'papers' mapping")
    if not isinstance(data.get("scene"), dict):
        raise ValueError(f"{path} must contain a top-level 'scene' mapping")
    return data


def selected_paper(config: dict, paper_id: str | None) -> tuple[str, dict]:
    selected = paper_id or config.get("default_paper")
    papers = config["papers"]
    if selected not in papers:
        choices = ", ".join(sorted(papers))
        raise ValueError(f"Unknown paper {selected!r}. Available papers: {choices}")
    if not isinstance(selected, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", selected):
        raise ValueError("Paper ID must be a safe name")
    paper = papers[selected]
    if not isinstance(paper, dict):
        raise ValueError(f"papers.{selected} must be a mapping")
    for key in ("pdf", "images", "blend"):
        if not isinstance(paper.get(key), str) or not paper[key].strip():
            raise ValueError(f"papers.{selected}.{key} must be a nonempty path")
    return selected, paper


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def generated_page(path: Path) -> bool:
    return bool(re.fullmatch(r"page_[0-9]+\.(?:jpg|jpeg|png)", path.name, re.IGNORECASE))


def validate_variant(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError("Variant must be a safe number or name")
    if value.isdigit() and int(value) < 1:
        raise ValueError("Numeric variants are 1-based")
    return value


def write_json(path: Path, data: dict, preserve: bool = True) -> None:
    path = Path(path)
    content = (json.dumps(data, indent=2) + "\n").encode()
    if path.is_symlink():
        raise ValueError(f"Refusing symlink output: {path}")
    if path.is_file() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if preserve and path.is_file():
        history = path.parent / "history"
        history.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(path, history / f"{path.stem}_{stamp}{path.suffix}")
    fd, name = tempfile.mkstemp(prefix=".paper-stack-json-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def stable_seed(*parts: object) -> int:
    payload = "::".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def variant_source_seed(random_config: dict, variant: str) -> tuple[int, dict]:
    seeds = random_config.get("seeds") or []
    numeric_index: int | None = None
    try:
        numeric_index = int(variant) - 1
    except ValueError:
        numeric_index = None

    if numeric_index is not None and numeric_index < 0:
        raise ValueError("Numeric variants are 1-based. Use VARIANT=1 or a name.")

    if seeds:
        if numeric_index is None:
            seed_index = stable_seed("variant-index", variant) % len(seeds)
        else:
            seed_index = numeric_index % len(seeds)
        source_seed = int(seeds[seed_index])
        return source_seed, {
            "seed_source": "random.seeds",
            "seed_index": seed_index,
            "seed_count": len(seeds),
        }

    base_seed = random_config.get("seed", 0)
    source_seed = stable_seed("variant", base_seed, variant)
    return source_seed, {"seed_source": "derived"}


def random_seed_pair(random_config: dict) -> tuple[int, int, dict]:
    seeds = [int(seed) for seed in random_config.get("seeds") or []]
    if not seeds:
        raise ValueError("Random variant mode requires at least one configured random.seeds entry.")

    stack_seed_index = secrets.randbelow(len(seeds))
    asset_seed_index = secrets.randbelow(len(seeds))
    stack_seed = seeds[stack_seed_index]
    asset_seed = seeds[asset_seed_index]
    return stack_seed, asset_seed, {
        "seed_source": "random.seeds",
        "stack_seed_index": stack_seed_index,
        "asset_seed_index": asset_seed_index,
        "seed_count": len(seeds),
    }


def random_config_for_variant(
    random_config: dict,
    variant: str | None,
    random_variant: bool = False,
) -> tuple[dict, dict | None]:
    config = copy.deepcopy(random_config)
    if variant is not None and random_variant:
        raise ValueError("Use either --variant or --random-variant, not both.")
    if variant is None and not random_variant:
        return config, None

    if variant is not None:
        validate_variant(variant)
    base_stack_seed = config.get("stack_seed")
    base_asset_seed = config.get("asset_seed")
    config["base_stack_seed"] = base_stack_seed
    config["base_asset_seed"] = base_asset_seed

    if random_variant:
        stack_seed, asset_seed, metadata = random_seed_pair(config)
        config["stack_seed"] = stack_seed
        config["asset_seed"] = asset_seed
        variant_metadata = {
            "id": "random",
            "mode": "random",
            "stack_seed": stack_seed,
            "asset_seed": asset_seed,
            **metadata,
        }
        return config, variant_metadata

    source_seed, metadata = variant_source_seed(config, variant)
    config["variant_source_seed"] = source_seed
    config["stack_seed"] = stable_seed(source_seed, variant, "stack")
    config["asset_seed"] = stable_seed(source_seed, variant, "assets")

    variant_metadata = {
        "id": variant,
        "mode": "deterministic",
        "source_seed": source_seed,
        "stack_seed": config["stack_seed"],
        "asset_seed": config["asset_seed"],
        **metadata,
    }
    return config, variant_metadata


def write_assets_json(args: argparse.Namespace) -> int:
    assets_path = resolve_path(args.assets)
    data = load_assets(assets_path)
    data["project_root"] = str(ROOT)

    output = resolve_path(args.output)
    write_json(output, data)
    print(output)
    return 0


def preprocess(args: argparse.Namespace) -> int:
    config = load_pipeline(resolve_path(args.config))
    paper_id, paper = selected_paper(config, args.paper)
    preprocess_config = config.get("preprocess", {})

    pdf_path = resolve_path(args.pdf or paper["pdf"])
    image_dir = resolve_path(args.images or paper["images"])
    dpi = args.dpi if args.dpi is not None else int(preprocess_config.get("dpi", 600))
    image_format = preprocess_config.get("image_format", "JPEG")
    extension = preprocess_config.get("extension", "jpg")

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF does not exist: {pdf_path}")

    if dpi <= 0:
        raise ValueError("DPI must be positive")
    if image_dir.is_symlink():
        raise ValueError("Image output directory may not be a symlink")
    image_dir.mkdir(parents=True, exist_ok=True)
    previous = [p for p in image_dir.iterdir() if generated_page(p)]
    if any(p.is_symlink() or not p.is_file() for p in previous):
        raise ValueError("Generated page outputs must be regular files")
    # Complete conversion first, so conversion failures leave existing pages intact.
    with tempfile.TemporaryDirectory(prefix=".paper-stack-pages-", dir=image_dir.parent) as d:
        staged = Path(d)
        pages = convert_from_path(pdf_path, dpi=dpi)
        if not pages:
            raise ValueError("The PDF contains no renderable pages")
        names = set()
        for index, image in enumerate(pages):
            name = f"page_{index}.{extension}"
            image.save(staged / name, image_format)
            image.close()
            names.add(name)
        if previous:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            history = image_dir / "history" / stamp
            history.mkdir(parents=True)
            for old in previous:
                shutil.copy2(old, history / old.name)
        for name in names:
            os.replace(staged / name, image_dir / name)
        for old in previous:
            if old.name not in names:
                old.unlink()

    print(f"{paper_id}: wrote {len(pages)} page images to {image_dir}")
    return 0


def stack_settings(config: dict, layout=None, thickness=None, gap=None) -> dict:
    settings = copy.deepcopy(config)
    mode = layout or settings.get("layout", "fan")
    if mode not in {"fan", "stack"}:
        raise ValueError("LAYOUT must be fan or stack")
    if mode != "stack" and (thickness is not None or gap is not None):
        raise ValueError("STACK_PAGE_THICKNESS and STACK_PAGE_GAP require LAYOUT=stack")
    settings["layout"] = mode
    compact = settings.setdefault("compact", {})
    compact.setdefault("frame_stack", True)
    if not isinstance(compact["frame_stack"], bool):
        raise ValueError("compact.frame_stack must be a boolean")
    defaults = {"page_thickness": 0.0012, "page_gap": 0.00008,
                "rotation_sigma": 0.10, "rotation_limit": 0.25,
                "position_sigma": 0.0005, "position_limit": 0.0015,
                "outlier_fraction": 0.08, "outlier_distance": 0.008, "outlier_rotation": 0.18, "edge_curl": 0.0035, "paper_grain_distance": 0.00015,
                "paper_surface_scale": 1.5, "paper_surface_strength": 0.5, "paper_surface_distance": 0.5,
                "paper_surface_seed": 0.0, "paper_surface_falloff": 1.0,
                "camera_margin": 1.12, "camera_elevation_degrees": 35.0, "camera_fstop": 4.0}
    for key, default in defaults.items():
        value = thickness if key == "page_thickness" and thickness is not None else gap if key == "page_gap" and gap is not None else compact.get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"compact.{key} must be a finite number") from exc
        if not math.isfinite(value) or value < 0 or (key == "page_thickness" and value == 0):
            raise ValueError(f"compact.{key} must be finite and nonnegative (thickness must be positive)")
        compact[key] = value
    if compact["camera_margin"] < 1 or not 5 <= compact["camera_elevation_degrees"] <= 85 or compact["camera_fstop"] <= 0:
        raise ValueError("Stack camera requires margin >= 1, elevation 5..85 degrees and positive f-stop")
    if compact["paper_surface_falloff"] <= 0:
        raise ValueError("compact.paper_surface_falloff must be positive")
    if compact["outlier_fraction"] > 1:
        raise ValueError("compact.outlier_fraction must be between 0 and 1")
    uv = compact.setdefault("focus_uv", [0.5, 0.76])
    if not isinstance(uv, (list, tuple)) or len(uv) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in uv):
        raise ValueError("compact.focus_uv must contain two normalized coordinates")
    lighting = compact.get("lighting", {})
    for key in ("spot_size_degrees", "energy", "radius", "fill_energy"):
        if key in lighting:
            value = lighting[key]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key == "spot_size_degrees" and not 0 < value <= 180):
                raise ValueError(f"Invalid compact.lighting.{key}")
    return settings


def write_scene_json(args: argparse.Namespace) -> int:
    config = load_pipeline(resolve_path(args.config))
    assets = load_assets(resolve_path(args.assets))
    paper_id, paper = selected_paper(config, args.paper)
    random_config, variant_metadata = random_config_for_variant(
        config.get("random", {}),
        args.variant,
        args.random_variant,
    )
    output_blend = args.output_blend
    mode = stack_settings(config["scene"].get("stack", {}), getattr(args, "layout", None),
        getattr(args, "stack_page_thickness", None), getattr(args, "stack_page_gap", None))["layout"]
    layout_stem = paper_id + ("_stack" if mode == "stack" else "")
    if output_blend is None:
        if args.variant is not None:
            output_blend = f"prj/variants/{layout_stem}_v{args.variant}.blend"
        elif args.random_variant:
            output_blend = f"prj/variants/{layout_stem}_random.blend"
        elif mode == "stack":
            output_blend = f"prj/{layout_stem}.blend"

    # Rendering a random layout keeps its recorded seeds; explicit builds draw anew.
    if getattr(args, "reuse_random", False) and args.random_variant and Path(args.output).is_file():
        old = json.loads(Path(args.output).read_text())
        if old.get("variant", {}).get("mode") == "random" and old.get("random", {}).get("seeds") == config.get("random", {}).get("seeds"):
            random_config, variant_metadata = old["random"], old["variant"]
    scene = copy.deepcopy(config["scene"])
    scene["stack"] = stack_settings(scene.get("stack", {}), getattr(args, "layout", None),
        getattr(args, "stack_page_thickness", None), getattr(args, "stack_page_gap", None))
    render = scene.setdefault("render", {})
    for key in ("samples", "resolution", "denoise"):
        value = getattr(args, key, None)
        if value is not None:
            render[key] = value
    scene_data = {
        "project_root": str(ROOT),
        "paper_id": paper_id,
        "paper": {
            "pdf": str(resolve_path(getattr(args, "pdf", None) or paper["pdf"])),
            "images": str(resolve_path(getattr(args, "images", None) or paper["images"])),
            "blend": str(resolve_path(output_blend or paper["blend"])),
            "render": str(resolve_path(paper.get("render", f"render/{paper_id}.png"))),
        },
        "random": random_config,
        "scene": scene,
        "assets": assets["assets"],
    }
    if variant_metadata:
        scene_data["variant"] = variant_metadata

    output = resolve_path(args.output)
    write_json(output, scene_data)
    print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paper_stack")
    parser.add_argument("--config", default="config/pipeline.yml")
    parser.add_argument("--assets", default="config/assets.yml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    preprocess_parser = subparsers.add_parser("preprocess")
    preprocess_parser.add_argument("--paper", default=None)
    preprocess_parser.add_argument("--pdf", default=None)
    preprocess_parser.add_argument("--images", default=None)
    preprocess_parser.add_argument("--dpi", type=int, default=None)

    assets_json = subparsers.add_parser("assets-json")
    assets_json.add_argument("--output", default="build/assets.json")

    scene_json = subparsers.add_parser("scene-json")
    scene_json.add_argument("--paper", default=None)
    scene_json.add_argument("--pdf", default=None)
    scene_json.add_argument("--images", default=None)
    scene_json.add_argument("--layout", choices=["fan", "stack"], default=None)
    scene_json.add_argument("--stack-page-thickness", type=float, default=None)
    scene_json.add_argument("--stack-page-gap", type=float, default=None)
    scene_json.add_argument("--output", default=None)
    scene_json.add_argument("--output-blend", default=None)
    variant_group = scene_json.add_mutually_exclusive_group()
    variant_group.add_argument("--variant", default=None)
    variant_group.add_argument("--random-variant", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preprocess":
        return preprocess(args)
    if args.command == "assets-json":
        return write_assets_json(args)
    if args.command == "scene-json":
        if args.output is None:
            config = load_pipeline(resolve_path(args.config))
            paper_id, _ = selected_paper(config, args.paper)
            mode = stack_settings(config["scene"].get("stack", {}), args.layout,
                args.stack_page_thickness, args.stack_page_gap)["layout"]
            paper_id += "_stack" if mode == "stack" else ""
            if args.variant is None and not args.random_variant:
                args.output = f"build/{paper_id}.scene.json"
            elif args.random_variant:
                args.output = f"build/variants/{paper_id}_random.scene.json"
            else:
                args.output = f"build/variants/{paper_id}_v{args.variant}.scene.json"
        return write_scene_json(args)
    raise ValueError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
