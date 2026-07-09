# PDF Paper Stack

Generate 3D mockup paper stack from pdf file like:

![example](render/cicc24.png)

## Workflow

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

The new scene is saved as `prj/<paper>.blend`, for example `prj/ofc25.blend`.
Camera, render, stack, light, background, paper, and asset settings live in
`config/pipeline.yml` and `config/assets.yml`; they are no longer encoded in
the output filename.

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

Render defaults to the newest existing `prj/variants/<paper>_*.blend` when one
exists, so this renders the latest variant for the paper:

```sh
make render PAPER_ID=ofc25
```

Force the base `prj/<paper>.blend` render with:

```sh
make render PAPER_ID=ofc25 RENDER_AUTO_VARIANT=0
```

Resolve local assets before rendering:

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
