"""UTF-8 stdout/stderr for long-running CLI workers on Windows (redirected logs)."""

from __future__ import annotations

import logging
import sys


def configure_worker_stdio_utf8() -> None:
    """Reconfigure process streams and existing logging StreamHandlers to UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass

    for handler in logging.root.handlers:
        _reconfigure_handler_stream(handler)
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            for handler in logger.handlers:
                _reconfigure_handler_stream(handler)


def _reconfigure_handler_stream(handler: logging.Handler) -> None:
    if not isinstance(handler, logging.StreamHandler):
        return
    stream = handler.stream
    if stream is not None and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass
