"""Migrations must produce exactly the schema the models declare (catches a forgotten `alembic revision`)."""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.db import Base


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.cmd_opts = type("o", (), {"x": [f"url={url}"]})()
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    assert diff == [], diff
