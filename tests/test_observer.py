from unittest.mock import patch
from core.observer import summary
from core.observer import collect_log_templates

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

def test_summary_schema():
    cfg = {
        "project": "chaos",
        "experiment": "TEST-1",
        "services": {},
        "backlog_check": {"container": "chaos-redis", "cmd": ["redis-cli", "LLEN", "votes"]},
    }

    with patch("core.observer.docker_events", return_value=[]), \
         patch("core.probes.backlog", return_value=3), \
         patch("core.observer.collect_log_templates", return_value={}):
        result = summary(
            t_start=100,
            t_end=110,
            cfg=cfg,
            queue_start=1,
            queue_end=3,
            accepted_count=10,
            delivered_count=8,
            kill_switch="test stop",
            stuck_services=["worker"],
            mttd_s=2.0,
            mttr_s=4.0,
        )

    assert result["experiment"] == "TEST-1"
    assert result["delivery"]["accepted"] == 10
    assert result["delivery"]["delivered"] == 8
    assert result["queue_depth"] == {"start": 1, "end": 3}
    assert result["kill_switch"] == "test stop"
    assert result["stuck_services"] == ["worker"]
    assert result["mttd_s"] == 2.0
    assert result["mttr_s"] == 4.0


def test_log_collection_window():
    cfg = {
        "services": {
            "worker": {"container": "chaos-worker"},
        }
    }

    with patch("core.observer.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "worker processed vote 123"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        collect_log_templates(cfg, 100, t_end=110)

    args = mock_run.call_args.args[0]
    assert "--since" in args
    assert args[args.index("--since") + 1] == "100"
    assert "--until" in args
    assert args[args.index("--until") + 1] == "110"


if __name__ == "__main__":
    tests = [
        test_summary_schema,
        test_log_collection_window,
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
