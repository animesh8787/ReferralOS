"""Imports every module that registers @handler task kinds. Add new task modules here."""
from . import tasks
from .services import contacts_import, jobs_tasks, profile_tasks, scoring_run  # noqa: F401


@tasks.handler("noop")
def _noop(ctx):
    ctx.update(progress=0.5)
    return {"ok": True}
