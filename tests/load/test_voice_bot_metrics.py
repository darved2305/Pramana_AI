"""Call-socket accounting uses the same clock events as the load bot."""

from __future__ import annotations

from voice_bot_common import CallSocketMetrics, latency_percentiles_ms


def test_call_socket_metrics_accumulate_three_way_hold_time() -> None:
    now = 10.0
    metrics = CallSocketMetrics(clock=lambda: now)
    metrics.opened("p_riya")
    metrics.opened("p_mahesh")
    metrics.opened("p_imran")
    now += 12.5
    metrics.closed("p_imran")
    metrics.closed("p_mahesh")
    metrics.closed("p_riya")

    assert metrics.snapshot() == {
        "opened": 3,
        "closed": 3,
        "peak_open": 3,
        "active": 0,
        "three_way_seconds": 12.5,
    }


def test_latency_percentiles_use_interpolated_caller_samples() -> None:
    assert latency_percentiles_ms([100, 200, 300, 400]) == {
        "p50_ms": 250.0,
        "p95_ms": 385.0,
        "sample_count": 4,
    }


def test_latency_percentiles_report_no_samples() -> None:
    assert latency_percentiles_ms([]) == {
        "p50_ms": None,
        "p95_ms": None,
        "sample_count": 0,
    }
