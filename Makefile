UV ?= /home/henning/.local/bin/uv
HA_HOST ?= root@homeassistant.home
HA_COMPONENT_DIR ?= /root/homeassistant/custom_components/surplus_power

.PHONY: sync test lint check prek prek-install deploy

sync:
	$(UV) sync --dev

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .

check: lint test

prek:
	uvx prek run --all-files

prek-install:
	uvx prek install

deploy: check
	rsync -av --delete --exclude='__pycache__/' --exclude='*.pyc' custom_components/surplus_power/ $(HA_HOST):$(HA_COMPONENT_DIR)/
