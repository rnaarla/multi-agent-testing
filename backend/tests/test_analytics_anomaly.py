from app.analytics.anomaly import MetricWindow, DriftAnalyzer, detect_latency_anomalies


def test_metric_window_stats():
    window = MetricWindow([1, 2, 3, 4])
    assert window.mean() == 2.5
    assert round(window.stdev(), 3) == 1.118


def test_drift_analyzer_detects_anomalies():
    baseline = MetricWindow([100, 110, 120, 115])
    candidate = MetricWindow([105, 500, 112])
    analyzer = DriftAnalyzer(threshold=2.5)
    result = analyzer.analyze(baseline, candidate)
    assert result.score > 2.5
    assert result.anomalies == [1]


def test_detect_latency_anomalies_helper():
    result = detect_latency_anomalies([100, 105, 110], [120, 130, 300], threshold=2.0)
    assert 2 in result.anomalies
from app.analytics.anomaly import AnomalyDetectionResult, detect_zscore_anomalies, moving_average


def test_detect_zscore_anomalies_identifies_outliers():
    series = [10, 11, 10, 9, 10, 50]
    result = detect_zscore_anomalies(series, z_threshold=2.0)
    assert isinstance(result, AnomalyDetectionResult)
    assert result.indices == [5]
    assert result.mean > 0
    assert result.stddev > 0


def test_moving_average_window():
    series = [1, 2, 3, 4]
    assert moving_average(series, 2) == [1, 1.5, 2.5, 3.5]


def test_moving_average_guardrails():
    series = [1, 2, 3]
    assert moving_average(series, 10) == series
    try:
        moving_average(series, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for non-positive window")

