# PDF Paper Stack

Generate 3D mockup paper stacks from configured PDF files:

![example render](img/example.png)

## Workflow

The default paper is `ofc25`. Select another configured paper with `PAPER_ID`
or `PAPER`; available IDs are listed in `config/pipeline.yml`.

Install Blender separately and make sure it is available as `blender`, or set
`BLENDER=/path/to/blender` when running the Makefile.

Create or update the Python environment:

```sh
make env
make env-update
```

Build a paper stack scene from the config:

```sh
make preprocess PAPER_ID=ofc25
make scene-json PAPER_ID=ofc25
make build-scene PAPER_ID=ofc25
```

`make scene-json` writes `build/<paper>.scene.json`, and `make build-scene`
builds `prj/<paper>.blend`, for example `prj/ofc25.blend`. Camera, render,
stack, light, background, paper, and asset settings live in
`config/pipeline.yml` and `config/assets.yml`.

Run preprocessing and scene building in one command:

```sh
make workflow PAPER_ID=ofc25
```

Build deterministic layout variants from the configured seed pool:

```sh
make workflow PAPER_ID=ofc25 VARIANT=3
make render PAPER_ID=ofc25 VARIANT=3
```

Variant builds save to `prj/variants/<paper>_v<variant>.blend` by default.
Numeric variants use the `random.seeds` pool in `config/pipeline.yml` and then
derive separate paper-stack and asset-jitter streams, so the pages, pen, and
paper clip move independently but reproducibly.

Build a seed-pool random layout variant:

```sh
make workflow PAPER_ID=ofc25 RANDOM_VARIANT=1
make render PAPER_ID=ofc25 RANDOM_VARIANT=1
```

Random variant builds save to `prj/variants/<paper>_random.blend` by default.
Each scene JSON generation randomly picks stack and asset seeds from
`random.seeds`, records the selected seed indices in
`build/variants/<paper>_random.scene.json`, and overwrites that random variant
unless you pass custom `SCENE_JSON` or `BLEND` paths.

Render outputs framed PNGs such as `render/ofc25_0001.png`. When no explicit
`VARIANT`, `RANDOM_VARIANT`, or `BLEND` is passed, render defaults to the newest
existing `prj/variants/<paper>_*.blend`; in that case output goes under
`render/variants/`.

```sh
make render PAPER_ID=ofc25
```

Force the base `prj/<paper>.blend` render with:

```sh
make render PAPER_ID=ofc25 RENDER_AUTO_VARIANT=0
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
