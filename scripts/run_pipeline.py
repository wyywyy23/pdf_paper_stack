"""One option-resolution and execution path for all Make pipeline targets."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

from PIL import Image
import paper_stack as ps


def boolean(value, name, default=False):
    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be 0/1, true/false, yes/no or on/off")


def positive(value, name):
    if not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def options(env=None):
    env = os.environ if env is None else env
    get = lambda key, default=None: env.get(key) or default
    config_path = ps.resolve_path(get("PIPELINE", "config/pipeline.yml"))
    config = ps.load_pipeline(config_path)
    if get("PAPER_ID") and get("PAPER") and get("PAPER_ID") != get("PAPER"):
        raise ValueError("PAPER_ID and PAPER disagree")
    paper_id, paper = ps.selected_paper(config, get("PAPER_ID") or get("PAPER"))
    variant = get("VARIANT")
    if variant is not None:
        ps.validate_variant(variant)
    random_variant = boolean(get("RANDOM_VARIANT"), "RANDOM_VARIANT")
    if variant is not None and random_variant:
        raise ValueError("Use either VARIANT or RANDOM_VARIANT, not both")
    stack = ps.stack_settings(config["scene"].get("stack", {}), get("LAYOUT"),
        get("STACK_PAGE_THICKNESS"), get("STACK_PAGE_GAP"))
    layout = stack["layout"]
    layout_stem = paper_id + ("_stack" if layout == "stack" else "")
    stem = f"{layout_stem}_v{variant}" if variant else f"{layout_stem}_random" if random_variant else layout_stem
    subdir = "variants" if variant or random_variant else ""
    project_dir = ps.resolve_path(get("PROJECT_DIR", "prj"))
    render_dir = ps.resolve_path(get("RENDER_DIR", "render"))
    blend = ps.resolve_path(get("BLEND", str(project_dir / subdir / f"{stem}.blend")))
    scene_json = ps.resolve_path(get("SCENE_JSON", str(Path("build") / subdir / f"{stem}.scene.json")))
    output = ps.resolve_path(get("RENDER_OUTPUT", str(render_dir / subdir / f"{stem}_####")))
    if scene_json.suffix.lower() != ".json" or blend.suffix.lower() != ".blend":
        raise ValueError("SCENE_JSON must end in .json and BLEND must end in .blend")
    if scene_json in {config_path, Path(ps.resolve_path(get("ASSETS", "config/assets.yml"))), ps.resolve_path(get("PDF", paper["pdf"]))}:
        raise ValueError("Scene output may not replace an input source")
    render = config["scene"].get("render", {})
    resolution = get("RESOLUTION")
    if resolution:
        match = re.fullmatch(r"([1-9][0-9]*)[xX]([1-9][0-9]*)", resolution)
        if not match:
            raise ValueError("RESOLUTION must be WIDTHxHEIGHT with positive dimensions")
        resolution = [int(match[1]), int(match[2])]
    return SimpleNamespace(config=str(config_path), assets=str(ps.resolve_path(get("ASSETS", "config/assets.yml"))),
        paper=paper_id, pdf=str(ps.resolve_path(get("PDF", paper["pdf"]))),
        images=str(ps.resolve_path(get("IMAGE_DIR", paper["images"]))),
        dpi=positive(get("DPI", config.get("preprocess", {}).get("dpi", 600)), "DPI"),
        samples=positive(get("SAMPLES", render.get("samples", 1024)), "SAMPLES"),
        resolution=resolution or render.get("resolution", [1920, 1080]),
        denoise=boolean(get("DENOISE"), "DENOISE", render.get("denoise", False)),
        layout=layout, layout_stem=layout_stem,
        stack_page_thickness=stack["compact"]["page_thickness"] if layout == "stack" else None,
        stack_page_gap=stack["compact"]["page_gap"] if layout == "stack" else None,
        variant=variant, random_variant=random_variant, output=str(scene_json), output_blend=str(blend),
        render_output=str(output), frame=positive(get("RENDER_FRAME", 1), "RENDER_FRAME"),
        auto_variant=boolean(get("RENDER_AUTO_VARIANT"), "RENDER_AUTO_VARIANT"),
        explicit_blend=bool(get("BLEND")), explicit_render_output=bool(get("RENDER_OUTPUT")),
        quality_override={k for k in ["SAMPLES", "RESOLUTION", "DENOISE"] if get(k) is not None},
        project_dir=project_dir, render_dir=render_dir, blender=get("BLENDER", "blender"),
        assets_json=ps.resolve_path(get("ASSETS_JSON", "build/assets.json")),
        smoke_blend=ps.resolve_path(get("ASSETS_SMOKE_BLEND", str(Path(tempfile.gettempdir()) / "pdf_paper_stack_assets_smoke.blend"))))


@contextmanager
def pipeline_lock():
    lockdir = Path(tempfile.gettempdir()) / "pdf-paper-stack-locks"
    lockdir.mkdir(exist_ok=True)
    key = hashlib.sha256(str(ps.ROOT).encode()).hexdigest()
    with (lockdir / key).open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def archive(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"Output may not be a symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"Output must be a regular file: {path}")
        directory = path.parent / "history"
        directory.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(path, directory / f"{path.stem}_{stamp}{path.suffix}")


def run(command):
    subprocess.run([str(x) for x in command], check=True)


def preprocess(o, force=False):
    image_dir = Path(o.images)
    cache = ps.ROOT / "build" / "page-cache" / (hashlib.sha256(str(image_dir).encode()).hexdigest() + ".json")
    config = ps.load_pipeline(Path(o.config))
    identity = {"pdf": o.pdf, "sha256": ps.file_hash(Path(o.pdf)), "dpi": o.dpi,
                "format": config.get("preprocess", {}), "producer": ps.file_hash(Path(ps.__file__))}
    if not force and cache.is_file():
        try:
            previous = json.loads(cache.read_text())
            actual = {p.name: ps.file_hash(p) for p in image_dir.iterdir() if ps.generated_page(p)}
            if previous["input"] == identity and previous["pages"] == actual and actual:
                print(f"{o.paper}: reusing {len(actual)} verified page images")
                return
        except (OSError, ValueError, KeyError):
            pass
    ps.preprocess(o)
    pages = {p.name: ps.file_hash(p) for p in image_dir.iterdir() if ps.generated_page(p)}
    ps.write_json(cache, {"input": identity, "pages": pages}, preserve=False)


def scene_json(o, reuse_random=False):
    o.reuse_random = reuse_random
    ps.write_scene_json(o)


def build(o, allow_fallback=False, reuse_random=False):
    preprocess(o)
    scene_json(o, reuse_random=reuse_random)
    output = Path(o.output_blend)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Blender writes a new staging file; failed builds never replace a saved scene.
    with tempfile.TemporaryDirectory(prefix=".paper-stack-build-", dir=output.parent) as d:
        staged = Path(d) / output.name
        run([o.blender, "--background", "--factory-startup", "--python-exit-code", "1",
             "--python", ps.ROOT / "scripts/blender_build_scene.py", "--", "--scene-json", o.output,
             "--output", staged] + (["--allow-blendkit-fallback"] if allow_fallback else []))
        if not staged.is_file() or staged.stat().st_size == 0:
            raise RuntimeError("Blender reported success but produced no scene")
        archive(output)
        os.replace(staged, output)


def render(o):
    # Old automatic latest-variant selection is now an explicit opt-in.
    if o.auto_variant and not o.explicit_blend and not o.variant and not o.random_variant:
        choices = list((o.project_dir / "variants").glob(f"{o.layout_stem}_*.blend"))
        if o.layout == "fan":
            choices = [p for p in choices if not p.stem.startswith(f"{o.paper}_stack_")]
        if choices:
            selected = max(choices, key=lambda p: p.stat().st_mtime_ns)
            o.output_blend = str(selected)
            o.explicit_blend = True
            if not o.explicit_render_output:
                o.render_output = str(o.render_dir / "variants" / f"{selected.stem}_####")
    if not o.explicit_blend:
        build(o, reuse_random=True)
    source = Path(o.output_blend)
    if not source.is_file():
        raise FileNotFoundError(f"Scene does not exist: {source}")
    output = Path(o.render_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"#+", lambda m: str(o.frame).zfill(len(m[0])), output.name)
    if "#" not in output.name:
        name += f"{o.frame:04d}"
    final = output.parent / (name if name.lower().endswith(".png") else name + ".png")
    # Render into an empty directory and validate a fresh PNG, not an old output.
    with tempfile.TemporaryDirectory(prefix=".paper-stack-render-", dir=output.parent) as d:
        prefix = Path(d) / "frame_####"
        expression = None
        if o.quality_override:
            expression = "import bpy;s=bpy.context.scene;"
            if "RESOLUTION" in o.quality_override:
                expression += f"s.render.resolution_x={o.resolution[0]};s.render.resolution_y={o.resolution[1]};s.render.resolution_percentage=100;"
            if "SAMPLES" in o.quality_override:
                expression += f"s.cycles.samples={o.samples};"
            if "DENOISE" in o.quality_override:
                expression += f"s.cycles.use_denoising={o.denoise!r};"
        command = [o.blender, "--background", source, "--python-exit-code", "1"]
        if expression:
            command += ["--python-expr", expression]
        run(command + ["--render-output", prefix, "--render-format", "PNG", "--render-frame", str(o.frame)])
        staged = Path(d) / f"frame_{o.frame:04d}.png"
        if not staged.is_file():
            raise RuntimeError("Blender reported success but produced no PNG")
        with Image.open(staged) as image:
            if image.format != "PNG":
                raise RuntimeError("Render is not a PNG")
            image.verify()
        archive(final)
        os.replace(staged, final)
    print(f"Rendered successfully: {final}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preprocess", "assets-json", "scene-json", "build-scene",
        "build-scene-blendkit", "workflow", "preprocess-build", "publish", "render", "assets-check",
        "assets-smoke", "assets-check-blendkit", "assets-smoke-blendkit", "check-tools", "blender-info"])
    command = parser.parse_args(argv).command
    o = options()
    with pipeline_lock():
        if command in {"check-tools", "blender-info"}:
            run([o.blender, "--background", "--version"])
        elif command == "preprocess":
            preprocess(o, force=True)
        elif command == "scene-json":
            scene_json(o)
        elif command in {"build-scene", "build-scene-blendkit", "workflow", "preprocess-build"}:
            build(o, allow_fallback=command.endswith("-blendkit"))
        elif command in {"publish", "render"}:
            if command == "publish":
                build(o)
                o.explicit_blend = True
            render(o)
        else:
            args = SimpleNamespace(assets=o.assets, output=str(o.assets_json))
            ps.write_assets_json(args)
            if command != "assets-json":
                smoke = "smoke" in command
                run([o.blender, "--background"] + ([] if command.endswith("-blendkit") else ["--factory-startup"]) +
                    ["--python-exit-code", "1", "--python", ps.ROOT / "scripts/blender_assets.py", "--",
                     "--manifest-json", o.assets_json, "--action", "append-smoke" if smoke else "check"] +
                    (["--allow-blendkit-fallback"] if command.endswith("-blendkit") else []) +
                    (["--output-blend", o.smoke_blend] if smoke else []))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"PDF Paper Stack failed: {exc}") from exc
