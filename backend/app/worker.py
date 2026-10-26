"""Run: python -m app.worker"""
import logging

from . import handlers  # noqa: F401  (registers task handlers)
from .crypto import RedactFilter
from .tasks import worker_loop

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().addFilter(RedactFilter())
    worker_loop()
