"""Imports every module that registers @handler task kinds. Add new task modules here."""
from . import tasks


@tasks.handler("noop")
def _noop(ctx):
    ctx.update(progress=0.5)
    return {"ok": True}
