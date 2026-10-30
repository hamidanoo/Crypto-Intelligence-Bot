import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Configure structured, single-line logging for the backend.

    Secrets must never be passed to log calls. Callers are responsible
    for logging identifiers and outcomes only, never tokens or keys.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
        force=True,
    )
