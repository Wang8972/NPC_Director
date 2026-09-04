from scripts.run_p4_gate import FAULTS, FUNCTIONAL, RECORDED
from scripts.run_p4_live_eval import CASES


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
