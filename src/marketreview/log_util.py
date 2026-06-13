"""
Minimal file-logging utility.  Writes to logs/ at the repo root.

One file per module, overwritten on each process start (mode='w').
No date in filename — no cleanup needed.

Usage:
    from marketreview.log_util import get_logger
    log = get_logger(__name__)
    log.info("hello")
"""

import logging
import os


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger that writes to ``logs/{sanitized_name}.log`` under the
    repository root.  File is overwritten on first handler creation (each
    process start).  DEBUG-level, UTF-8.
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

    safe_name = name.replace(".", "_")
    log_file = os.path.join(log_dir, f"{safe_name}.log")

    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)

    return logger
