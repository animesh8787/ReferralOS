import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import handlers  # noqa: F401
from . import models  # noqa: F401  (registers tables)
from .api import admin, auth, me, profile
from .config import get_settings
from .crypto import RedactFilter

logging.getLogger().addFilter(RedactFilter())

app = FastAPI(title="ReferralOS API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
for r in (auth.router, me.router, admin.router, profile.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}
