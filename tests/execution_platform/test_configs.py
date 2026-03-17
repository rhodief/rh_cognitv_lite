"""Phase 2 unit tests — RetryConfig, TimeoutConfig, ParallelConfig."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from rh_cognitv_lite.execution_platform.models import ParallelConfig, RetryConfig, TimeoutConfig


def test_retry_config_defaults():
    cfg = RetryConfig()
    assert cfg.max_attempts == 3
    assert cfg.base_delay == 0.1
    assert cfg.max_delay == 30.0
    assert cfg.multiplier == 2.0


def test_retry_config_backoff_formula():
    cfg = RetryConfig(base_delay=0.1, multiplier=2.0, max_delay=30.0)
    # attempt 1 → 0.1 * 2^0 = 0.1
    # attempt 2 → 0.1 * 2^1 = 0.2
    # attempt 3 → 0.1 * 2^2 = 0.4
    # attempt 4 → 0.1 * 2^3 = 0.8
    # attempt 5 → 0.1 * 2^4 = 1.6
    expected = [0.1, 0.2, 0.4, 0.8, 1.6]
    for attempt, exp in enumerate(expected, start=1):
        assert abs(cfg.delay_for(attempt) - exp) < 1e-9

    # Verify cap: very high attempt should not exceed max_delay
    assert cfg.delay_for(100) == cfg.max_delay


def test_retry_config_backoff_capped_at_max_delay():
    cfg = RetryConfig(base_delay=10.0, multiplier=10.0, max_delay=30.0)
    assert cfg.delay_for(3) == 30.0  # 10 * 10^2 = 1000 → capped at 30


def test_timeout_config_defaults():
    cfg = TimeoutConfig()
    assert cfg.each_execution_timeout == 60.0
    assert cfg.total_timeout == 300.0


def test_parallel_config_defaults():
    cfg = ParallelConfig()
    assert cfg.max_concurrency == 5
    assert cfg.error_strategy == "fail_slow"


def test_parallel_config_fail_fast_accepted():
    cfg = ParallelConfig(error_strategy="fail_fast")
    assert cfg.error_strategy == "fail_fast"


def test_parallel_config_invalid_error_strategy():
    with pytest.raises(ValidationError):
        ParallelConfig(error_strategy="unknown")


def test_configs_importable_from_package():
    from rh_cognitv_lite.execution_platform import ParallelConfig, RetryConfig, TimeoutConfig

    assert RetryConfig is not None
    assert TimeoutConfig is not None
    assert ParallelConfig is not None
