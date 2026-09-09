from scripts.analyze_pivot_performance import analyze
from scripts.run_p4_gate import FAULTS, FUNCTIONAL, RECORDED, run_node
from scripts.run_p4_live_eval import CASES, _distribution


def test_p4_frozen_matrix_sizes_and_ids() -> None:
    assert list(RECORDED) == [
        "EV-G01",
        "EV-G02",
        "EV-G03",
        "EV-G04",
        "EV-K01",
        "EV-K02",
        "EV-K03",
        "EV-K04",
        "EV-A01",
        "EV-A02",
        "EV-A03",
        "EV-A04",
        "EV-C01",
        "EV-C02",
        "EV-C03",
        "EV-C04",
        "EV-S01",
        "EV-S02",
    ]
    assert list(FUNCTIONAL) == [f"TC-{index:02d}" for index in range(1, 17)]
    assert list(FAULTS) == [f"FT-{index:02d}" for index in range(1, 13)]


def test_p4_live_matrix_is_ten_cases_with_three_trials_at_runtime() -> None:
    assert [case.case_id for case in CASES] == [
        "EV-G04",
        "EV-K02",
        "EV-K04",
        "EV-A01",
        "EV-A02",
        "EV-C01",
        "EV-C02",
        "EV-C03",
        "EV-C04",
        "EV-S01",
    ]


def test_p4_route_artifacts_require_production_bounded_chain() -> None:
    legacy = {
        "status": "pass",
        "session_report": {"route_success_counts": {"cooperation": 1}},
    }
    bounded = {
        "status": "pass",
        "session_report": {
            "route_success_counts": {"cooperation": 1},
            "production_orchestration": True,
        },
    }

    assert run_node("artifact:p3_mock:cooperation", legacy)["status"] == "fail"
    assert run_node("artifact:p3_mock:cooperation", bounded)["status"] == "pass"


def test_latency_distribution_uses_tail_percentile() -> None:
    result = _distribution([1, 2, 3, 4, 100])
    assert result["p50"] == 3
    assert result["p95"] == 4
    assert result["max"] == 100


def test_pivot_analysis_computes_residual_stage_tokens_and_cost() -> None:
    report = {
        "status": "pass",
        "model": "test-model",
        "results": [
            {
                "case_id": "EV-X",
                "trial": 1,
                "status": "accepted",
                "profile": {
                    "model_calls": [
                        {
                            "total_ms": 100,
                            "stages_ms": {"cli_startup": 10, "model": 60},
                            "usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 40,
                                "output_tokens": 20,
                            },
                        }
                    ]
                },
            }
        ],
    }
    result = analyze(
        report,
        input_rate=2.0,
        cached_input_rate=1.0,
        output_rate=4.0,
    )

    assert result["stage_distributions_ms"]["post_turn_process_exit"]["p50"] == 30
    assert result["usage"]["uncached_input_tokens"] == 60
    assert result["pricing"]["estimated_total_cost"] == 0.00024
