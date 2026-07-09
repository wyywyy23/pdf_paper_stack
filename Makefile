ENV_NAME := pdf-paper-stack
BLENDER ?= blender

PAPER_ID ?=
PAPER ?=
ifneq ($(strip $(PAPER_ID)),)
ifneq ($(strip $(PAPER)),)
ifneq ($(strip $(PAPER_ID)),$(strip $(PAPER)))
$(error Use either PAPER_ID or PAPER, not both)
endif
endif
override PAPER := $(PAPER_ID)
else ifeq ($(strip $(PAPER)),)
override PAPER := ofc25
endif
VARIANT ?=
RANDOM_VARIANT ?=
PIPELINE ?= config/pipeline.yml
PDF ?=
IMAGE_DIR ?=
PROJECT_DIR ?= prj
RENDER_DIR ?= render
RENDER_FRAME ?= 1
ASSETS ?= config/assets.yml
ASSETS_SMOKE_BLEND ?= /private/tmp/pdf_paper_stack_assets_smoke.blend
BLEND_ORIGIN := $(origin BLEND)
RENDER_OUTPUT_ORIGIN := $(origin RENDER_OUTPUT)
RENDER_AUTO_VARIANT ?= 1

ifneq ($(strip $(VARIANT)),)
ifneq ($(strip $(RANDOM_VARIANT)),)
$(error Use either VARIANT or RANDOM_VARIANT, not both)
endif
VARIANT_ARGS := --variant "$(VARIANT)"
DEFAULT_BLEND := $(PROJECT_DIR)/variants/$(PAPER)_v$(VARIANT).blend
DEFAULT_RENDER_OUTPUT := $(RENDER_DIR)/variants/$(PAPER)_v$(VARIANT)_\#\#\#\#
DEFAULT_SCENE_JSON := build/variants/$(PAPER)_v$(VARIANT).scene.json
else ifneq ($(strip $(RANDOM_VARIANT)),)
VARIANT_ARGS := --random-variant
DEFAULT_BLEND := $(PROJECT_DIR)/variants/$(PAPER)_random.blend
DEFAULT_RENDER_OUTPUT := $(RENDER_DIR)/variants/$(PAPER)_random_\#\#\#\#
DEFAULT_SCENE_JSON := build/variants/$(PAPER)_random.scene.json
else
VARIANT_ARGS :=
DEFAULT_BLEND := $(PROJECT_DIR)/$(PAPER).blend
DEFAULT_RENDER_OUTPUT := $(RENDER_DIR)/$(PAPER)_\#\#\#\#
DEFAULT_SCENE_JSON := build/$(PAPER).scene.json
endif

BLEND ?= $(DEFAULT_BLEND)
RENDER_OUTPUT ?= $(DEFAULT_RENDER_OUTPUT)
ASSETS_JSON ?= build/assets.json
SCENE_JSON ?= $(DEFAULT_SCENE_JSON)
RANDOM_SCENE_FORCE :=
ifneq ($(strip $(RANDOM_VARIANT)),)
RANDOM_SCENE_FORCE := force-random-scene
endif

PREPROCESS_ARGS := --paper "$(PAPER)"
ifneq ($(strip $(PDF)),)
PREPROCESS_ARGS += --pdf "$(PDF)"
endif
ifneq ($(strip $(IMAGE_DIR)),)
PREPROCESS_ARGS += --images "$(IMAGE_DIR)"
endif

.PHONY: \
	help \
	env env-update env-remove env-info \
	preprocess \
	assets-json assets-check assets-smoke assets-check-blendkit assets-smoke-blendkit \
	scene-json build-scene build-scene-blendkit workflow preprocess-build \
	render blender-info check-tools force-random-scene

help:
	@printf "PDF Paper Stack workflow\n"
	@printf "\n"
	@printf "Environment:\n"
	@printf "  make env              Create or update the conda environment\n"
	@printf "  make env-update       Update the conda environment and prune stale packages\n"
	@printf "  make env-remove       Remove the conda environment\n"
	@printf "  make env-info         Show Python and key package paths inside the env\n"
	@printf "\n"
	@printf "Workflow:\n"
	@printf "  make preprocess       Convert the configured PDF to img/<paper>/page_N.jpg\n"
	@printf "  make scene-json       Materialize per-paper Blender JSON config\n"
	@printf "  make build-scene      Build prj/<paper>.blend from page images and assets\n"
	@printf "  make workflow         Run preprocess, then build-scene\n"
	@printf "  make preprocess-build Alias for workflow\n"
	@printf "  make build-scene VARIANT=3 Build deterministic variant in prj/variants/\n"
	@printf "  make build-scene RANDOM_VARIANT=1 Build seed-pool random variant in prj/variants/\n"
	@printf "  make assets-check     Resolve local/cached assets from config/assets.yml\n"
	@printf "  make assets-smoke     Append resolved assets into a temporary .blend\n"
	@printf "  make assets-*-blendkit Same asset checks, with BlendKit ID fallback enabled\n"
	@printf "  make render           Render latest variant .blend, or base .blend if no variant exists\n"
	@printf "\n"
	@printf "Variables:\n"
	@printf "  PAPER=%s\n" "$(PAPER)"
	@printf "  PAPER_ID=%s (alias for PAPER)\n" "$(PAPER)"
	@printf "  VARIANT=%s\n" "$(VARIANT)"
	@printf "  RANDOM_VARIANT=%s\n" "$(RANDOM_VARIANT)"
	@printf "  RENDER_AUTO_VARIANT=%s\n" "$(RENDER_AUTO_VARIANT)"
	@printf "  PIPELINE=%s\n" "$(PIPELINE)"
	@printf "  PDF=%s\n" "$(PDF)"
	@printf "  ASSETS=%s\n" "$(ASSETS)"
	@printf "  SCENE_JSON=%s\n" "$(SCENE_JSON)"
	@printf "  BLEND=%s\n" "$(BLEND)"
	@printf "  RENDER_OUTPUT=%s\n" "$(RENDER_OUTPUT)"
	@printf "\n"
	@printf "Examples:\n"
	@printf "  make env\n"
	@printf "  make preprocess PAPER_ID=ofc25 PDF=pdf/wangOFC25.pdf\n"
	@printf "  make workflow PAPER_ID=ofc25 VARIANT=3\n"
	@printf "  make workflow PAPER_ID=ofc25 RANDOM_VARIANT=1\n"
	@printf "  make render PAPER_ID=ofc25\n"
	@printf "  make render PAPER_ID=ofc25 RANDOM_VARIANT=1\n"
	@printf "  make render PAPER_ID=ofc25 RENDER_AUTO_VARIANT=0\n"

env:
	conda env create -f environment.yml || conda env update -f environment.yml --prune

env-update:
	conda env update -f environment.yml --prune

env-remove:
	conda env remove -n $(ENV_NAME)

env-info:
	conda run -n $(ENV_NAME) python -c "import sys; print(sys.executable); print(sys.version)"
	conda run -n $(ENV_NAME) python -c "import pdf2image, PIL, yaml; print('pdf2image:', pdf2image.__file__); print('Pillow:', PIL.__version__); print('PyYAML:', yaml.__version__)"

check-tools:
	conda --version
	@command -v "$(BLENDER)" >/dev/null || (printf "Blender not found on PATH: %s\n" "$(BLENDER)"; exit 1)
	$(BLENDER) --background --version

preprocess:
	conda run -n $(ENV_NAME) python scripts/paper_stack.py --config "$(PIPELINE)" preprocess $(PREPROCESS_ARGS)

$(ASSETS_JSON): $(ASSETS) scripts/paper_stack.py
	@mkdir -p "$(dir $(ASSETS_JSON))"
	conda run -n $(ENV_NAME) python scripts/paper_stack.py --assets "$(ASSETS)" assets-json --output "$(ASSETS_JSON)"

assets-json: $(ASSETS_JSON)

assets-check: check-tools $(ASSETS_JSON)
	$(BLENDER) --background --factory-startup --python scripts/blender_assets.py -- --manifest-json "$(ASSETS_JSON)" --action check

assets-smoke: check-tools $(ASSETS_JSON)
	$(BLENDER) --background --factory-startup --python scripts/blender_assets.py -- --manifest-json "$(ASSETS_JSON)" --action append-smoke --output-blend "$(ASSETS_SMOKE_BLEND)"

assets-check-blendkit: check-tools $(ASSETS_JSON)
	$(BLENDER) --background --python scripts/blender_assets.py -- --manifest-json "$(ASSETS_JSON)" --action check --allow-blendkit-fallback

assets-smoke-blendkit: check-tools $(ASSETS_JSON)
	$(BLENDER) --background --python scripts/blender_assets.py -- --manifest-json "$(ASSETS_JSON)" --action append-smoke --allow-blendkit-fallback --output-blend "$(ASSETS_SMOKE_BLEND)"

force-random-scene:

$(SCENE_JSON): $(PIPELINE) $(ASSETS) scripts/paper_stack.py $(RANDOM_SCENE_FORCE)
	@mkdir -p "$(dir $(SCENE_JSON))"
	conda run -n $(ENV_NAME) python scripts/paper_stack.py --config "$(PIPELINE)" --assets "$(ASSETS)" scene-json --paper "$(PAPER)" --output "$(SCENE_JSON)" --output-blend "$(BLEND)" $(VARIANT_ARGS)

scene-json: $(SCENE_JSON)

build-scene: check-tools $(SCENE_JSON)
	@mkdir -p "$(dir $(BLEND))"
	$(BLENDER) --background --factory-startup --python scripts/blender_build_scene.py -- --scene-json "$(SCENE_JSON)" --output "$(BLEND)"

build-scene-blendkit: check-tools $(SCENE_JSON)
	@mkdir -p "$(dir $(BLEND))"
	$(BLENDER) --background --python scripts/blender_build_scene.py -- --scene-json "$(SCENE_JSON)" --output "$(BLEND)" --allow-blendkit-fallback

workflow:
	$(MAKE) preprocess
	$(MAKE) build-scene

preprocess-build: workflow

render: check-tools
	@blend="$(BLEND)"; \
	output="$(RENDER_OUTPUT)"; \
	if [ "$(RENDER_AUTO_VARIANT)" = "1" ] && [ -z "$(strip $(VARIANT))" ] && [ -z "$(strip $(RANDOM_VARIANT))" ] && [ "$(BLEND_ORIGIN)" = "undefined" ]; then \
		latest=$$(ls -t "$(PROJECT_DIR)"/variants/"$(PAPER)"_*.blend 2>/dev/null | head -n 1); \
		if [ -n "$$latest" ]; then \
			blend="$$latest"; \
			if [ "$(RENDER_OUTPUT_ORIGIN)" = "undefined" ]; then \
				stem=$$(basename "$$latest" .blend); \
				output="$(RENDER_DIR)/variants/$${stem}_####"; \
			fi; \
		fi; \
	fi; \
	test -f "$$blend" || (printf "Blend file not found: %s\nRun make build-scene PAPER=%s first.\n" "$$blend" "$(PAPER)"; exit 1); \
	mkdir -p "$$(dirname "$$output")"; \
	printf "Rendering %s to %s\n" "$$blend" "$$output"; \
	$(BLENDER) --background "$$blend" --render-output "$$(cd "$$(dirname "$$output")" && pwd)/$$(basename "$$output")" --render-format PNG --render-frame $(RENDER_FRAME); \
	printf "Rendered frame %s with output prefix %s\n" "$(RENDER_FRAME)" "$$output"

blender-info:
	$(BLENDER) --background --version
