.DEFAULT_GOAL := help
ENV_NAME ?= pdf-paper-stack
CONDA ?= conda
BLENDER ?= blender
PYTHON ?=
ifeq ($(strip $(PYTHON)),)
RUN_PYTHON = "$(CONDA)" run --no-capture-output -n "$(ENV_NAME)" python
else
RUN_PYTHON = "$(PYTHON)"
endif

# Python resolves defaults from the selected configuration, once, for every target.
export PAPER_ID PAPER VARIANT RANDOM_VARIANT PIPELINE PDF IMAGE_DIR PROJECT_DIR
export RENDER_DIR RENDER_FRAME ASSETS SCENE_JSON BLEND RENDER_OUTPUT ASSETS_JSON
export ASSETS_SMOKE_BLEND RENDER_AUTO_VARIANT BLENDER DPI SAMPLES RESOLUTION DENOISE
export LAYOUT STACK_PAGE_THICKNESS STACK_PAGE_GAP

.PHONY: help env env-update env-remove env-info check-tools blender-info \
 preprocess assets-json scene-json build-scene build-scene-blendkit workflow \
 preprocess-build render publish assets-check assets-smoke \
 assets-check-blendkit assets-smoke-blendkit test

help:
	@printf '%s\n' 'PDF Paper Stack: make workflow, then make render; make publish runs both.' \
	 'Default paper: PIPELINE.default_paper (t-cpmt25 in the supplied config).' \
	 'PAPER_ID=<id> (PAPER alias); VARIANT=<1-based-number-or-name>; RANDOM_VARIANT=0|1.' \
	 'LAYOUT=fan|stack (default fan); stack uses physical page thickness for long documents.' \
	 'STACK_PAGE_THICKNESS=0.0012; STACK_PAGE_GAP=0.00008 (fractions of page height).' \
	 'PDF=<file>; IMAGE_DIR=<dir>; PIPELINE=<yaml>; ASSETS=<yaml>.' \
	 'DPI=<positive-int>; SAMPLES=<positive-int>; RESOLUTION=<width>x<height>; DENOISE=0|1.' \
	 'SCENE_JSON=<file>; BLEND=<file>; RENDER_OUTPUT=<prefix-with-####>; RENDER_FRAME=1.' \
	 'PROJECT_DIR=prj; RENDER_DIR=render; RENDER_AUTO_VARIANT=0 (explicit opt-in available).' \
	 'PYTHON=<executable> bypasses Conda; otherwise ENV_NAME=pdf-paper-stack.' \
	 'Outputs are refreshed safely; replaced scenes/configs/images are archived under history/.' \
	 'make test runs the regression suite.'

env:
	@listing=$$("$(CONDA)" env list --json) || exit $$?; \
	 printf '%s\n' "$$listing" | "$(CONDA)" run --no-capture-output -n base python -c 'import json,os,sys; name=sys.argv[1]; sys.exit(0 if any(os.path.basename(p)==name for p in json.load(sys.stdin)["envs"]) else 3)' "$(ENV_NAME)"; exists=$$?; \
	 if [ "$$exists" = 0 ]; then "$(CONDA)" env update -n "$(ENV_NAME)" -f environment.yml --prune; \
	 elif [ "$$exists" = 3 ]; then "$(CONDA)" env create -n "$(ENV_NAME)" -f environment.yml; else exit "$$exists"; fi

env-update:
	"$(CONDA)" env update -n "$(ENV_NAME)" -f environment.yml --prune

env-remove:
	"$(CONDA)" env remove -n "$(ENV_NAME)"

env-info:
	$(RUN_PYTHON) -c 'import sys,pdf2image,PIL,yaml; print(sys.executable); print(sys.version); print("Pillow:",PIL.__version__,"PyYAML:",yaml.__version__)'

check-tools blender-info preprocess assets-json scene-json build-scene build-scene-blendkit workflow preprocess-build render publish assets-check assets-smoke assets-check-blendkit assets-smoke-blendkit:
	$(RUN_PYTHON) scripts/run_pipeline.py $@

test:
	$(RUN_PYTHON) -m unittest discover -s tests -v
