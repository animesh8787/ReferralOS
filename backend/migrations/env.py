from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401  (register all tables)
from app.config import get_settings
from app.db import Base

target_metadata = Base.metadata


def _url() -> str:
    return context.get_x_argument(as_dictionary=True).get("url") or get_settings().database_url


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=conn.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
