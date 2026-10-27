"""Run: python -m app.worker"""
import logging

from . import handlers  # noqa: F401  (registers task handlers)
from .crypto import install_log_redaction
from .tasks import worker_loop

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    install_log_redaction()
    worker_loop()
