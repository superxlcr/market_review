"""
Concurrent LLM batch-call utility.

Used by DashboardService to parallelise independent AI summary calls
(e.g. SH index + CZ index, or multiple industry sectors).
"""
from __future__ import annotations

import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from marketreview.llm import LLMClient
from marketreview.log_util import get_logger

log = get_logger(__name__)

FAIL_PLACEHOLDER = "AI 摘要暂时不可用"


def batch_chat(
    llm: LLMClient,
    system_prompt: str,
    tasks: list[dict],
    max_workers: int = 4,
    progress_cb: Callable | None = None,
    fail_placeholder: str = FAIL_PLACEHOLDER,
) -> dict[str, str]:
    """Run multiple LLM chat calls concurrently.

    Args:
        llm: LLM client instance (shared across threads).
        system_prompt: Shared system prompt for all calls.
        tasks: List of task dicts, each with:
            - "label" (str): unique identifier for this task
            - "user_message" (str): the user-prompt content
        max_workers: Max concurrent LLM calls (default 4).
        progress_cb: Optional callback(phase, current, total, label).
            - phase="start": all tasks submitted (total known)
            - phase="progress": a task just completed (label=task label)
            - phase="done": all tasks completed
        fail_placeholder: Value to use when a single task fails (does not
            raise — the caller decides how to handle placeholders).

    Returns:
        Dict mapping label → LLM response text (or fail_placeholder on error).
    """
    if not tasks:
        return {}

    total = len(tasks)
    workers = min(max_workers, total)
    labels = [t["label"] for t in tasks]

    _t_start = _time.perf_counter()

    # Track per-task start time for individual elapsed logging
    _task_start: dict[str, float] = {}

    def _call_one(label: str, user_msg: str) -> tuple[str, str]:
        _task_start[label] = _time.perf_counter()
        try:
            content = llm.chat(system_prompt, user_msg)
            elapsed = _time.perf_counter() - _task_start[label]
            log.info("batch_chat task=%s elapsed=%.1fs status=ok", label, elapsed)
            return (label, content)
        except Exception:
            import traceback as _tb
            elapsed = _time.perf_counter() - _task_start[label]
            log.warning("batch_chat task=%s elapsed=%.1fs status=failed\n%s",
                       label, elapsed, _tb.format_exc())
            return (label, fail_placeholder)

    results: dict[str, str] = {}

    log.info("batch_chat start: tasks=%d workers=%d labels=%s", total, workers, labels)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_call_one, t["label"], t["user_message"]): t["label"]
            for t in tasks
        }

        if progress_cb:
            progress_cb("start", 0, total, "")

        completed = 0
        for future in as_completed(future_map):
            label, content = future.result()
            results[label] = content
            completed += 1
            if progress_cb:
                progress_cb("progress", completed, total, label)

    if progress_cb:
        progress_cb("done", total, total, "")

    total_elapsed = _time.perf_counter() - _t_start
    failed = sum(1 for v in results.values() if v == fail_placeholder)
    log.info("batch_chat done: total=%.1fs failed=%d/%d",
             total_elapsed, failed, total)

    return results
