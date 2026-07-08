from __future__ import annotations

import argparse
import copy
import hashlib
import json
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
    paper = papers[selected]
    if not isinstance(paper, dict):
        raise ValueError(f"papers.{selected} must be a mapping")
    return selected, paper


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


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


def random_config_for_variant(
    random_config: dict,
    variant: str | None,
) -> tuple[dict, dict | None]:
    config = copy.deepcopy(random_config)
    if variant is None:
        return config, None

    source_seed, metadata = variant_source_seed(config, variant)
    base_stack_seed = config.get("stack_seed")
    base_asset_seed = config.get("asset_seed")

    config["base_stack_seed"] = base_stack_seed
    config["base_asset_seed"] = base_asset_seed
    config["variant_source_seed"] = source_seed
    config["stack_seed"] = stable_seed(source_seed, variant, "stack")
    config["asset_seed"] = stable_seed(source_seed, variant, "assets")

    variant_metadata = {
        "id": variant,
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
    dpi = args.dpi or int(preprocess_config.get("dpi", 600))
    image_format = preprocess_config.get("image_format", "JPEG")
    extension = preprocess_config.get("extension", "jpg")

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF does not exist: {pdf_path}")

    image_dir.mkdir(parents=True, exist_ok=True)
    pages = convert_from_path(pdf_path, dpi=dpi)
    for index, image in enumerate(pages):
        image.save(image_dir / f"page_{index}.{extension}", image_format)

    print(f"{paper_id}: wrote {len(pages)} page images to {image_dir}")
    return 0


def write_scene_json(args: argparse.Namespace) -> int:
    config = load_pipeline(resolve_path(args.config))
    assets = load_assets(resolve_path(args.assets))
    paper_id, paper = selected_paper(config, args.paper)
    random_config, variant_metadata = random_config_for_variant(
        config.get("random", {}),
        args.variant,
    )
    output_blend = args.output_blend
    if output_blend is None and args.variant is not None:
        output_blend = f"prj/variants/{paper_id}_v{args.variant}.blend"

    scene_data = {
        "project_root": str(ROOT),
        "paper_id": paper_id,
        "paper": {
            "pdf": str(resolve_path(paper["pdf"])),
            "images": str(resolve_path(paper["images"])),
            "blend": str(resolve_path(output_blend or paper["blend"])),
            "render": str(resolve_path(paper.get("render", f"render/{paper_id}.png"))),
        },
        "random": random_config,
        "scene": config["scene"],
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
    scene_json.add_argument("--output", default=None)
    scene_json.add_argument("--output-blend", default=None)
    scene_json.add_argument("--variant", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preprocess":
        return preprocess(args)
    if args.command == "assets-json":
        return write_assets_json(args)
    if args.command == "scene-json":
        if args.output is None:
            paper_id, _ = selected_paper(load_pipeline(resolve_path(args.config)), args.paper)
            if args.variant is None:
                args.output = f"build/{paper_id}.scene.json"
            else:
                args.output = f"build/variants/{paper_id}_v{args.variant}.scene.json"
        return write_scene_json(args)
    raise ValueError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
