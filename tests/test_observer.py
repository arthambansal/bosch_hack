
from core.observer import (
    normalize_log,
    mine_log_templates,
    detect_anomalies,
)


def test_normalize_log():
    result = normalize_log(
        "ERROR from 192.168.1.10 at 0xAB12 request 404"
    )
    assert "<IP>" in result
    assert "<HEX>" in result
    assert "<NUM>" in result


def test_mine_log_templates():
    logs = [
        "Worker failed with code 123",
        "Worker failed with code 456",
        "Redis connected",
    ]
    templates = mine_log_templates(logs)

    assert templates["Worker failed with code <NUM>"] == 2
    assert templates["Redis connected"] == 1


def test_probe_error_anomaly():
    metrics = {
        "probe_error_rate": {"vote_write": 0.10},
        "queue_depth": None,
        "events": [],
    }

    anomalies = detect_anomalies(metrics)

    assert any(
        item["type"] == "probe_error_rate"
        for item in anomalies
    )


def test_queue_missing_measurements():
    metrics = {
        "probe_error_rate": {},
        "queue_depth": {"start": None, "end": 5},
        "events": [],
    }

    anomalies = detect_anomalies(metrics)

    assert not any(
        item["type"] == "queue_growth"
        for item in anomalies
    )


def test_container_exit_anomaly():
    metrics = {
        "probe_error_rate": {},
        "queue_depth": None,
        "events": [
            {
                "event": "die",
                "service": "worker",
                "exit_code": 1,
            }
        ],
    }

    anomalies = detect_anomalies(metrics)

    assert any(
        item["type"] == "container_exit"
        and item["service"] == "worker"
        for item in anomalies
    )


if __name__ == "__main__":
    tests = [
        test_normalize_log,
        test_mine_log_templates,
        test_probe_error_anomaly,
        test_queue_missing_measurements,
        test_container_exit_anomaly,
    ]

    for test in tests:
        test()
        print(f"PASS {test.__name__}")

    print("ALL OBSERVER TESTS PASSED")
