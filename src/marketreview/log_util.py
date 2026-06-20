"""
Minimal file-logging utility.  Writes to logs/ at the repo root.

- One file per module, overwritten on each process start (mode='w').
- A shared ``logs/errors.log`` captures WARNING and above from ALL loggers.
- No date in filename — no cleanup needed.

Usage:
    from marketreview.log_util import get_logger
    log = get_logger(__name__)
    log.info("hello")
"""

import logging
import os

# ── module-private: set up root-level error log once ──
_error_handler: logging.Handler | None = None


def _ensure_error_log(log_dir: str) -> None:
    """Create a single root-handler that writes WARNING+ to errors.log."""
    global _error_handler
    if _error_handler is not None:
        return

    os.makedirs(log_dir, exist_ok=True)
    error_file = os.path.join(log_dir, "errors.log")

    _error_handler = logging.FileHandler(error_file, mode="w", encoding="utf-8")
    _error_handler.setLevel(logging.WARNING)
    _error_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    # Attach to root logger so ALL loggers' WARNING+ messages are captured.
    root = logging.getLogger()
    root.addHandler(_error_handler)
    # Don't set root level below WARNING — child loggers control their own levels.
    root.setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger that writes to ``logs/{sanitized_name}.log`` under the
    repository root.  File is overwritten on first handler creation (each
    process start).  DEBUG-level, UTF-8.

    Also ensures a shared ``logs/errors.log`` exists that collects WARNING+
    messages from every logger in the process.
    """
    # Locate repo root:  src/marketreview/log_util.py
    #                  → src/marketreview
    #                  → src
    #                  → repo root
    pkg_dir = os.path.dirname(os.path.abspath(__file__))       # .../src/marketreview
    src_dir = os.path.dirname(pkg_dir)                         # .../src
    project_root = os.path.dirname(src_dir)                    # .../repo-root

    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # ── per-module DEBUG log ──
    safe_name = name.replace(".", "_")
    log_file = os.path.join(log_dir, f"{safe_name}.log")

    logger = logging.getLogger(name)
    # Force fresh log file on every process start: close old handlers,
    # delete the old file, then create a new writable handler.
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
    if os.path.exists(log_file):
        os.remove(log_file)
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)

    # ── ensure shared error log ──
    _ensure_error_log(log_dir)

    return logger
