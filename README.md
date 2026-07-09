# PDF Paper Stack

Generate 3D mockup paper stacks from configured PDF files:

![example render](img/example.png)

The checked-in preview image is rendered from the bundled `t-cpmt25` sample
PDF. Other source PDFs, converted page images, Blender scene files, and render
outputs are generated or supplied locally and are not committed.

## What You Need To Supply

- Blender, installed separately and available as `blender`, or passed as
  `BLENDER=/path/to/blender`.
- The source PDF for any non-sample paper you want to build. Put it at the
  `pdf` path for that paper in `config/pipeline.yml`, or pass
  `PDF=/path/to/paper.pdf` when running `make preprocess`.
- Generated page images under `img/<paper>/page_N.jpg`. These are produced by
  `make preprocess` from your local PDF and are ignored by Git.
- Any replacement assets you configure in `config/assets.yml`. The repository
  keeps the currently configured local assets under `prj/assets/`; if you change
  those paths, provide your own `.blend` files or use the BlendKit fallback
  targets.

## Workflow

The default paper is `t-cpmt25`. Select another configured paper with
`PAPER_ID` or `PAPER`; available IDs are listed in `config/pipeline.yml`.

The default `t-cpmt25` sample PDF is included at:

```text
pdf/Wang et al. - 2025 - Co-Designed Silicon Photonics Chip IO for Energy-Efficient Petascale Connectivity.pdf
```

To build a different local copy without editing the config:

```sh
make preprocess PAPER_ID=t-cpmt25 PDF=/path/to/your-paper.pdf
```

Create or update the Python environment:

```sh
make env
make env-update
```

Build a paper stack scene from the config:

```sh
make preprocess PAPER_ID=t-cpmt25
make scene-json PAPER_ID=t-cpmt25
make build-scene PAPER_ID=t-cpmt25
```

`make scene-json` writes `build/<paper>.scene.json`, and `make build-scene`
builds `prj/<paper>.blend`, for example `prj/t-cpmt25.blend`. Camera, render,
stack, light, background, paper, and asset settings live in
`config/pipeline.yml` and `config/assets.yml`.

Run preprocessing and scene building in one command:

```sh
make workflow PAPER_ID=t-cpmt25
```

Build deterministic layout variants from the configured seed pool:

```sh
make workflow PAPER_ID=t-cpmt25 VARIANT=3
make render PAPER_ID=t-cpmt25 VARIANT=3
```

Variant builds save to `prj/variants/<paper>_v<variant>.blend` by default.
Numeric variants use the `random.seeds` pool in `config/pipeline.yml` and then
derive separate paper-stack and asset-jitter streams, so the pages, pen, and
paper clip move independently but reproducibly.

Build a seed-pool random layout variant:

```sh
make workflow PAPER_ID=t-cpmt25 RANDOM_VARIANT=1
make render PAPER_ID=t-cpmt25 RANDOM_VARIANT=1
```

Random variant builds save to `prj/variants/<paper>_random.blend` by default.
Each scene JSON generation randomly picks stack and asset seeds from
`random.seeds`, records the selected seed indices in
`build/variants/<paper>_random.scene.json`, and overwrites that random variant
unless you pass custom `SCENE_JSON` or `BLEND` paths.

Render outputs framed PNGs such as `render/t-cpmt25_0001.png`. These outputs
are ignored by Git. When no explicit `VARIANT`, `RANDOM_VARIANT`, or `BLEND` is
passed, render defaults to the newest existing `prj/variants/<paper>_*.blend`;
in that case output goes under `render/variants/`.

```sh
make render PAPER_ID=t-cpmt25
```

Force the base `prj/<paper>.blend` render with:

```sh
make render PAPER_ID=t-cpmt25 RENDER_AUTO_VARIANT=0
```

Validate local assets before building scenes:

```sh
make assets-check
make assets-smoke
```

Assets are configured in `config/assets.yml`. The loader checks project-local `.blend`
files first, then cache globs such as `~/blenderkit_data/...`. BlendKit
`asset_base_id` values are kept as an explicit fallback:

```sh
make assets-check-blendkit
make assets-smoke-blendkit
```
