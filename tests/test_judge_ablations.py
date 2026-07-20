from pathlib import Path

from eval.ablations import VariantSpec, run_ablation_suite
from eval.judge import calibrate, load_calibration


def test_recorded_judge_calibration_meets_threshold() -> None:
    examples = load_calibration(Path("eval/judge/calibration.jsonl"))
    report = calibrate(examples)

    assert report.total == 10
    assert report.accuracy >= 0.8


def test_ablation_runner_compares_variants() -> None:
    baseline = Path("eval/baselines/recorded.jsonl")
    report = run_ablation_suite(
        Path("eval/cases/golden.jsonl"),
        [
            VariantSpec(name="single", baseline_path=baseline),
            VariantSpec(name="dynamic", baseline_path=baseline),
        ],
    )

    assert report.cases >= 10
    assert [item.name for item in report.variants] == ["single", "dynamic"]
    assert all(item.schema_pass_rate == 1 for item in report.variants)
    assert all(item.routing_failure_rate is None for item in report.variants)
