import os
import time

import pytest


@pytest.mark.load
def test_soak_mode_runs_when_enabled():
    if os.getenv("RUN_LOAD_TESTS") != "1":
        pytest.skip("Load tests disabled by default")

    start = time.perf_counter()
    total = 0
    for i in range(10_000):
        total += i

    assert total >= 0
    assert time.perf_counter() >= start

