import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from . import handlers  # noqa: F401
from . import models  # noqa: F401  (registers tables)
from .api import account, admin, auth, contacts, imports, jobs, matching, me, outreach, profile, scoring, tailoring
from .config import get_settings
from .crypto import install_log_redaction

install_log_redaction()

app = FastAPI(title="ReferralOS API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def reject_nul_in_query(request: Request, call_next):
    # PostgreSQL cannot store NUL in text; reject it for every route instead of failing with a 500 (SQLite would accept it)
    if "%00" in request.url.query:
        return JSONResponse({"detail": "Invalid character in query"}, status_code=422)
    return await call_next(request)


for r in (auth.router, me.router, admin.router, profile.router, imports.router, contacts.router, scoring.router, jobs.router, matching.router, tailoring.router, outreach.router, account.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}
