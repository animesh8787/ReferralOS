"""Background task send_outbox: sends approved, queued emails with pacing. Runs in the worker, never inside an HTTP request."""
import time

from ...tasks import handler
from . import send, settings as osettings


def heartbeat_sleep(ctx, chunk: float = 20.0):
    """Sleep in short chunks and refresh the task heartbeat, so a long pacing delay is never mistaken for a crashed worker."""
    def _sleep(seconds: float) -> None:
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            time.sleep(min(chunk, left))
            ctx.update()
    return _sleep


@handler("send_outbox")
def send_outbox(ctx):
    cfg = osettings.get(ctx.db)
    return send.send_outbox(ctx.db, cfg, sleep=heartbeat_sleep(ctx), commit_each=True)
