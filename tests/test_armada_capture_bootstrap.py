"""Unit tests for armada_capture_bootstrap controller logic."""

import sys
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "py_modules") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "py_modules"))

try:
    from py_modules.armada_capture_bootstrap import bootstrap
except ImportError:
    from armada_capture_bootstrap import bootstrap

VALID_IDS = [
    "0123456789abcdef",
    "1234567890abcdef",
    "2345678901abcdef",
    "3456789012abcdef",
]


def healthy_report(**overrides):
    res = {
        "passed": True,
        "stage": "completed",
        "code": 0,
        "dispatches_completed": 2,
        "error_callbacks": 0,
        "destroy_ok": True,
        "device_healthy": True,
        "cleanup_wait_ok": True,
        "destroy_code": 0,
    }
    res.update(overrides)
    return {"exit_code": 0, "result": res}


def failure_report(stage="upscale_dispatch", **overrides):
    res = {
        "passed": False,
        "stage": stage,
        "code": 1,
        "dispatches_completed": 1 if stage == "upscale_dispatch" else 0,
        "error_callbacks": 0,
        "device_healthy": True,
        "cleanup_wait_ok": True,
    }
    if stage == "upscale_dispatch":
        res["destroy_ok"] = True
        res["destroy_code"] = 0
    res.update(overrides)
    return {"exit_code": 1, "result": res}


class TestArmadaCaptureBootstrap(unittest.TestCase):
    def test_four_progressive_failures_then_final_pass(self):
        calls = []

        def run_probe(idx, ready, final):
            calls.append((idx, ready, final))
            return failure_report("upscale_dispatch") if not final else healthy_report()

        def collect(idx, missing):
            return {sorted(missing)[0]}

        res = bootstrap(VALID_IDS, run_probe, collect, threading.Event())
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[-1], (4, frozenset(VALID_IDS), True))
        self.assertEqual(res["discovery_attempts"], 4)
        self.assertEqual(res["validated_ids"], sorted(VALID_IDS))
        self.assertFalse(res["gameplay_tested"])
        self.assertFalse(res["quality_tested"])

    def test_all_four_first_discovery_still_separate_final(self):
        calls = []

        def run_probe(idx, ready, final):
            calls.append((idx, ready, final))
            return healthy_report()

        def collect(idx, missing):
            return set(missing)

        res = bootstrap(VALID_IDS, run_probe, collect, threading.Event())
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], (0, frozenset(), False))
        self.assertEqual(calls[1], (1, frozenset(VALID_IDS), True))
        self.assertEqual(res["discovery_attempts"], 1)

    def test_healthy_discovery_incomplete_outputs_continues(self):
        calls = []

        def run_probe(idx, ready, final):
            calls.append((idx, ready, final))
            return healthy_report()

        def collect(idx, missing):
            return set(sorted(missing)[:2])

        res = bootstrap(VALID_IDS, run_probe, collect, threading.Event())
        self.assertEqual(len(calls), 3)
        self.assertEqual(res["discovery_attempts"], 2)

    def test_no_progress_abort_after_one(self):
        calls = []

        def run_probe(idx, ready, final):
            calls.append(idx)
            return healthy_report()

        def collect(idx, missing):
            return set()

        with self.assertRaises(ValueError):
            bootstrap(VALID_IDS, run_probe, collect, threading.Event())
        self.assertEqual(len(calls), 1)

    def test_unknown_and_repeated_ids_rejected(self):
        def run_probe(idx, ready, final):
            return healthy_report()

        with self.assertRaises(ValueError):
            bootstrap(VALID_IDS, run_probe, lambda i, m: {"ffffffffffffffff"}, threading.Event())

        with self.assertRaises(ValueError):
            bootstrap(VALID_IDS, run_probe, lambda i, m: list(m), threading.Event())

        step = 0

        def collect_repeat(idx, missing):
            nonlocal step
            step += 1
            return {VALID_IDS[0]}

        with self.assertRaises(ValueError):
            bootstrap(VALID_IDS, run_probe, collect_repeat, threading.Event())

    def test_malformed_and_arbitrary_failure_rejected(self):
        def bad_probe(report):
            return lambda idx, ready, final: report

        event = threading.Event()
        dummy_col = lambda i, m: set(m)
        cases = [
            {"exit_code": 1, "result": {"passed": False, "stage": "unknown", "code": 1, "device_healthy": True, "cleanup_wait_ok": True, "dispatches_completed": 0, "error_callbacks": 0}},
            healthy_report(code=1),
            {"exit_code": True, "result": healthy_report()["result"]},
            {"exit_code": 0, "result": "not_a_dict"},
            healthy_report(passed=1),
            healthy_report(stage=123),
            healthy_report(dispatches_completed=True),
        ]
        for c in cases:
            with self.subTest(case=c):
                with self.assertRaises(ValueError):
                    bootstrap(VALID_IDS, bad_probe(c), dummy_col, event)

    def test_device_loss_cleanup_failure_abort(self):
        event = threading.Event()
        dummy_col = lambda i, m: set(m)
        with self.assertRaises(ValueError):
            bootstrap(VALID_IDS, lambda i, r, f: healthy_report(device_healthy=False), dummy_col, event)
        with self.assertRaises(ValueError):
            bootstrap(VALID_IDS, lambda i, r, f: healthy_report(cleanup_wait_ok=False), dummy_col, event)

    def test_final_probe_failure_rejected(self):
        event = threading.Event()
        dummy_col = lambda i, m: set(m)
        bad_finals = [
            failure_report("upscale_dispatch"),
            healthy_report(destroy_ok=False),
            healthy_report(destroy_code=1),
            healthy_report(dispatches_completed=1),
            healthy_report(error_callbacks=1),
        ]
        for bf in bad_finals:
            def probe(i, r, f, rep=bf):
                return healthy_report() if not f else rep
            with self.subTest(rep=bf):
                with self.assertRaises(ValueError):
                    bootstrap(VALID_IDS, probe, dummy_col, event)

    def test_cancellation_points(self):
        evt = threading.Event()
        evt.set()
        with self.assertRaises(RuntimeError):
            bootstrap(VALID_IDS, lambda i, r, f: healthy_report(), lambda i, m: set(m), evt)

        evt = threading.Event()
        def probe_cancel_run(i, r, f):
            evt.set()
            return healthy_report()
        with self.assertRaises(RuntimeError):
            bootstrap(VALID_IDS, probe_cancel_run, lambda i, m: set(m), evt)

        evt = threading.Event()
        def collect_cancel(i, m):
            evt.set()
            return set(m)
        with self.assertRaises(RuntimeError):
            bootstrap(VALID_IDS, lambda i, r, f: healthy_report(), collect_cancel, evt)

        evt = threading.Event()
        def probe_cancel_final(i, r, f):
            if f:
                evt.set()
            return healthy_report()
        with self.assertRaises(RuntimeError):
            bootstrap(VALID_IDS, probe_cancel_final, lambda i, m: set(m), evt)

    def test_timeout_and_value_errors_propagate(self):
        def probe_timeout(i, r, f):
            raise TimeoutError("probe timeout")
        with self.assertRaises(TimeoutError):
            bootstrap(VALID_IDS, probe_timeout, lambda i, m: set(m), threading.Event())

        def collect_err(i, m):
            raise ValueError("hash mismatch")
        with self.assertRaises(ValueError):
            bootstrap(VALID_IDS, lambda i, r, f: healthy_report(), collect_err, threading.Event())

    def test_invalid_required_ids_rejected(self):
        event = threading.Event()
        dummy_p = lambda i, r, f: healthy_report()
        dummy_c = lambda i, m: set(m)
        bad_reqs = [
            "0123456789abcdef",
            b"0123456789abcdef",
            12345,
            VALID_IDS[:3],
            VALID_IDS + ["4567890123abcdef"],
            VALID_IDS[:3] + ["0123456789abcdeg"],
            VALID_IDS[:3] + ["0123456789ABCDEF"],
            VALID_IDS[:3] + ["0123456789abcde"],
            VALID_IDS[:3] + [VALID_IDS[0]],
        ]
        for br in bad_reqs:
            with self.subTest(req=br):
                with self.assertRaises((TypeError, ValueError)):
                    bootstrap(br, dummy_p, dummy_c, event)


if __name__ == "__main__":
    unittest.main()
