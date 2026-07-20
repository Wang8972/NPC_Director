.PHONY: install format lint test demo catalog eval eval-live eval-live-main-sub ablations judge-calibration api load-test verify

install:
	python3 -m pip install -e ".[dev]"

format:
	python3 -m ruff format .

lint:
	python3 -m ruff check .

test:
	python3 -m pytest

demo:
	python3 -m scripts.render_demo

catalog:
	python3 -m scripts.export_catalog

eval:
	python3 -m eval.runner --mode recorded

eval-live:
	python3 -m eval.runner --mode live

eval-live-main-sub:
	python3 -m eval.runner --mode live --architecture main_sub \
		--output eval/reports/live_main_sub.json

ablations:
	python3 -m eval.ablations --cases eval/cases/golden.jsonl \
		--variant single_agent=single_agent=eval/baselines/single_agent.jsonl \
		--variant main_sub_fixed=main_sub=eval/baselines/main_sub_fixed_all.jsonl \
		--variant main_sub_dynamic=main_sub=eval/baselines/main_sub_dynamic.jsonl \
		--variant no_memory=main_sub=eval/baselines/no_memory.jsonl \
		--variant full_lore=main_sub=eval/baselines/full_lore.jsonl \
		--output eval/reports/ablations.json

judge-calibration:
	python3 -m scripts.calibrate_judge

api:
	python3 -m npc_director.api

load-test:
	python3 -m scripts.load_test --output eval/reports/load_test.json

verify: lint test demo catalog eval ablations judge-calibration load-test
