import pytest

from scripts.load_test import run_load_profile


@pytest.mark.asyncio
async def test_offline_load_profile_meets_interaction_budget() -> None:
    report = await run_load_profile(turns=12, concurrency=4)

    assert report["turns"] == 12
    assert report["p95_ms"] < 5_000
    assert report["throughput_per_second"] > 0
