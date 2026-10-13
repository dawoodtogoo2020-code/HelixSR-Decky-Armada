"""
Armada Capture Bootstrap controller logic.
SPDX-License-Identifier: MIT
"""

from typing import Any, Callable, Dict, Iterable, Set


def _check_cancelled(cancelled: Any) -> None:
    if cancelled is None:
        return
    if hasattr(cancelled, "is_set"):
        if cancelled.is_set():
            raise RuntimeError("Cancelled")
    elif callable(cancelled):
        if cancelled():
            raise RuntimeError("Cancelled")


def _validate_report(report: Any, final: bool) -> None:
    if not isinstance(report, dict):
        raise ValueError("Probe report must be a dict")
    exit_code = report.get("exit_code")
    if type(exit_code) is not int:
        raise ValueError("exit_code must be an int (bool excluded)")
    res = report.get("result")
    if not isinstance(res, dict):
        raise ValueError("result must be a dict")
    passed = res.get("passed")
    if type(passed) is not bool:
        raise ValueError("passed must be a bool")
    stage = res.get("stage")
    if not isinstance(stage, str):
        raise ValueError("stage must be a str")
    code = res.get("code")
    if type(code) is not int:
        raise ValueError("code must be an int")
    disp = res.get("dispatches_completed")
    if type(disp) is not int:
        raise ValueError("dispatches_completed must be an int")
    err_cb = res.get("error_callbacks")
    if type(err_cb) is not int:
        raise ValueError("error_callbacks must be an int")
    dev_hlth = res.get("device_healthy")
    if type(dev_hlth) is not bool:
        raise ValueError("device_healthy must be a bool")
    clean_ok = res.get("cleanup_wait_ok")
    if type(clean_ok) is not bool:
        raise ValueError("cleanup_wait_ok must be a bool")

    is_healthy = (
        exit_code == 0
        and passed is True
        and stage == "completed"
        and code == 0
        and disp == 2
        and err_cb == 0
        and dev_hlth is True
        and clean_ok is True
        and type(res.get("destroy_ok")) is bool
        and res.get("destroy_ok") is True
        and type(res.get("destroy_code")) is int
        and res.get("destroy_code") == 0
    )
    if final:
        if not is_healthy:
            raise ValueError("Final probe failed healthy completion requirement")
        return

    if is_healthy:
        return

    is_recoverable = (
        exit_code == 1
        and passed is False
        and stage in ("context_create", "upscale_dispatch")
        and code != 0
        and dev_hlth is True
        and clean_ok is True
        and disp in (0, 1)
        and err_cb >= 0
    )
    if is_recoverable:
        if stage == "upscale_dispatch":
            if not (type(res.get("destroy_ok")) is bool and res.get("destroy_ok") is True):
                raise ValueError("upscale_dispatch requires destroy_ok True")
            if not (type(res.get("destroy_code")) is int and res.get("destroy_code") == 0):
                raise ValueError("upscale_dispatch requires destroy_code 0")
        return

    raise ValueError(f"Probe report failed validation: exit_code={exit_code}, stage={stage}")


def bootstrap(
    required: Iterable[str],
    run_probe: Callable[[int, frozenset, bool], Dict[str, Any]],
    collect: Callable[[int, frozenset], Set[str]],
    cancelled: Any,
) -> Dict[str, Any]:
    if isinstance(required, (str, bytes)):
        raise TypeError("required cannot be string or bytes")
    try:
        req_list = list(required)
    except TypeError:
        raise TypeError("required must be iterable")
    if len(req_list) != 4:
        raise ValueError("required must contain exactly 4 items")
    hex_chars = set("0123456789abcdef")
    for item in req_list:
        if not isinstance(item, str) or len(item) != 16 or any(c not in hex_chars for c in item):
            raise ValueError(f"Invalid required ID: {item!r}")
    req_set = frozenset(req_list)
    if len(req_set) != 4:
        raise ValueError("required IDs must be distinct")

    _check_cancelled(cancelled)
    ready: Set[str] = set()
    attempts = 0

    while attempts < 4 and len(ready) < 4:
        _check_cancelled(cancelled)
        report = run_probe(attempts, frozenset(ready), False)
        _check_cancelled(cancelled)
        _validate_report(report, final=False)

        missing = frozenset(req_set - ready)
        _check_cancelled(cancelled)
        accepted = collect(attempts, missing)
        _check_cancelled(cancelled)

        if type(accepted) not in (set, frozenset) or not accepted:
            raise ValueError("collect must return non-empty set or frozenset")
        if not accepted.issubset(missing):
            raise ValueError(f"collect returned invalid IDs: {accepted}")
        ready.update(accepted)
        attempts += 1
        if len(ready) == 4:
            break

    if len(ready) < 4:
        raise RuntimeError("Incomplete discovery after 4 attempts")

    _check_cancelled(cancelled)
    final_report = run_probe(attempts, frozenset(ready), True)
    _check_cancelled(cancelled)
    _validate_report(final_report, final=True)

    _check_cancelled(cancelled)
    return {
        "discovery_attempts": attempts,
        "validated_ids": sorted(req_set),
        "final_probe": final_report["result"],
        "gameplay_tested": False,
        "quality_tested": False,
    }
