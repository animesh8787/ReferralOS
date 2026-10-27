"""Performance harness. Starts a REAL API server and a SEPARATE worker process (queue mode, not inline), then drives N synthetic users
concurrently over HTTP and records what was actually measured. Nothing here is a claim; the numbers are whatever this machine produced.

    cd backend && uv run python ../scripts/perf.py --db sqlite --users 3 --out ../docs/PERF_sqlite.json
    cd backend && uv run python ../scripts/perf.py --db postgresql+psycopg://u:p@localhost:55432/perf --out ../docs/PERF_postgres.json
"""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
from tests import synth_contacts as sc  # noqa: E402

BASE = "http://127.0.0.1:8300"
PW = "correct-horse-9"


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))] * 1000, 1)


def timed(fn, *a, **k):
    t = time.perf_counter()
    r = fn(*a, **k)
    return r, time.perf_counter() - t


class Server:
    def __init__(self, db: str, data: Path):
        data.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{(data / 'perf.db').as_posix()}" if db == "sqlite" else db
        self.env = {**os.environ, "DATABASE_URL": url, "DATA_DIR": str(data), "TASKS_INLINE": "0", "ADAPTER_MODE": "mock", "PYTHONUNBUFFERED": "1"}
        self.data, self.procs = data, []

    def start(self):
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND, env=self.env, check=True, capture_output=True)
        self.procs.append(subprocess.Popen(["uv", "run", "uvicorn", "app.main:app", "--port", "8300", "--log-level", "warning"], cwd=BACKEND, env=self.env))
        self.procs.append(subprocess.Popen(["uv", "run", "python", "-m", "app.worker"], cwd=BACKEND, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for _ in range(120):
            try:
                if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(1)
        raise RuntimeError("server did not start")

    def python_procs(self):
        out = []
        for p in self.procs:
            try:
                root = psutil.Process(p.pid)
                out += [root] + root.children(recursive=True)
            except psutil.Error:
                pass
        return out

    def stop(self):
        for p in self.procs:
            try:
                for c in psutil.Process(p.pid).children(recursive=True):
                    c.kill()
                p.kill()
            except psutil.Error:
                pass


class MemSampler(threading.Thread):
    def __init__(self, server):
        super().__init__(daemon=True)
        self.server, self.peak, self.stop_ = server, 0, False

    def run(self):
        while not self.stop_:
            rss = 0
            for p in self.server.python_procs():
                try:
                    rss += p.memory_info().rss
                except psutil.Error:
                    pass
            self.peak = max(self.peak, rss)
            time.sleep(0.5)


def wait_tasks(c: httpx.Client, timeout=900):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        ts = c.get("/api/tasks").json()
        if not any(t["status"] in ("queued", "running") for t in ts):
            return time.perf_counter() - t0, [t for t in ts if t["status"] == "failed"]
        time.sleep(0.5)
    raise TimeoutError("tasks did not finish")


def user_run(i: int, args, data: Path) -> dict:
    out = {"user": i}
    c = httpx.Client(base_url=BASE, timeout=120)
    email = f"perf{i}.{int(time.time())}@example.com"
    c.post("/api/auth/signup", json={"email": email, "password": PW}).raise_for_status()
    tok = next(json.loads(f.read_text())["body"].split(": ")[-1] for f in sorted((data / "outbox").glob("*.json"), reverse=True) if json.loads(f.read_text())["to"] == email)
    c.post("/api/auth/verify", json={"token": tok}).raise_for_status()
    c.post("/api/auth/login", json={"email": email, "password": PW}).raise_for_status()
    c.headers["X-CSRF-Token"] = c.cookies["csrf"]
    for sec, d in (("personal", {"name": f"Perf User {i}", "email": email, "links": []}),
                   ("experience", {"title": "Backend Engineer", "organization": "Initech Sample", "start": "2020-01", "end": "present", "bullets": ["Built REST APIs in Python with PostgreSQL and Docker."]}),
                   ("education", {"institution": "Example State University", "degree": "B.Tech", "end": "2019-05", "expected": False, "coursework": []})):
        c.post("/api/profile/items", json={"section": sec, "data": d}).raise_for_status()
    for n in ("Python", "PostgreSQL", "Docker"):
        c.post("/api/profile/items", json={"section": "skill", "data": {"name": n}})
    c.put("/api/profile/preferences", json={"target_roles": ["Backend Engineer"], "locations": ["Remote"]})
    start = i * 3000  # overlapping people and companies across users on purpose

    def do_import(kind, data_bytes, prov):
        r = c.post("/api/imports", data={"kind": kind}, files={"file": (f"{kind}.csv", data_bytes, "text/csv")})
        r.raise_for_status()
        iid = r.json()["import_id"]
        t0 = time.perf_counter()
        c.post(f"/api/imports/{iid}/start", json={"provenance": prov} if prov else {}).raise_for_status()
        while c.get(f"/api/imports/{iid}").json()["status"] not in ("done", "failed"):
            time.sleep(0.3)
        return time.perf_counter() - t0, c.get(f"/api/imports/{iid}").json()

    li_bytes, hr_bytes = sc.to_csv(sc.LI_HEADER, sc.li_rows(args.linkedin, start=start)), sc.to_csv(sc.HR_HEADER, sc.hr_rows(args.hr, start=start))
    out["upload_bytes"] = {"linkedin": len(li_bytes), "hr": len(hr_bytes)}
    t, rep = do_import("linkedin", li_bytes, None)
    out["import_linkedin_s"], out["import_linkedin_rows_per_s"], out["import_linkedin_valid"] = round(t, 1), round(args.linkedin / t), rep["report"]["valid"]
    t_score, failed = wait_tasks(c)  # the follow-up scoring task queued by the import
    out["score_after_import_s"], out["failed_tasks_after_li"] = round(t_score, 1), len(failed)
    t, rep = do_import("hr", hr_bytes, "self_collected")
    out["import_hr_s"], out["import_hr_rows_per_s"], out["import_hr_valid"] = round(t, 1), round(args.hr / t), rep["report"]["valid"]
    wait_tasks(c)
    return out, c


def seed_jobs(user_ids: list[str], n: int, db_url: str):
    """500 public-style jobs + per-user links, inserted directly (the ATS adapters are tested elsewhere)."""
    os.environ["DATABASE_URL"] = db_url
    from app import db as appdb
    from app.models.contacts import Company
    from app.models.jobs import Job, JobSource, JobVerification, UserJob
    from app.util import utcnow
    appdb.reset_engine()
    s = appdb.new_session()
    comps = s.query(Company).all()
    now = utcnow()
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_synthetic
    rows = list(gen_synthetic.jobs(n))
    for k, r in enumerate(rows):
        co = comps[k % len(comps)]
        job = Job(company_id=co.id, title=r["title"], canonical_key=f"{r['title'].lower()}|{k}", location=r["location"], work_arrangement="remote" if r["location"] == "Remote" else "onsite",
                  employment_type="full_time", description=r["description"], apply_url=f"https://boards.example.com/{co.id[:6]}/{k}", status="ACTIVE_VERIFIED", last_verified=now)
        s.add(job)
        s.flush()
        s.add(JobSource(job_id=job.id, source_type="greenhouse", board_token=f"perf-{k % 20}", source_job_id=str(k)))
        s.add(JobVerification(job_id=job.id, source_type="greenhouse", kind="api_listed", detail={}))
        for uid in user_ids:
            s.add(UserJob(user_id=uid, job_id=job.id, origin="discovery"))
    s.commit()
    s.close()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite")
    ap.add_argument("--users", type=int, default=3)
    ap.add_argument("--linkedin", type=int, default=11000)
    ap.add_argument("--hr", type=int, default=5000)
    ap.add_argument("--jobs", type=int, default=500)
    ap.add_argument("--out", default=str(ROOT / "docs/PERF.json"))
    args = ap.parse_args()
    data = Path(tempfile.mkdtemp(prefix="referralos-perf-"))
    srv = Server(args.db, data)
    result = {"machine": {"os": platform.platform(), "cpus": psutil.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1), "python": platform.python_version()},
              "database": "sqlite" if args.db == "sqlite" else "postgresql", "args": vars(args), "note": "synthetic data only; one API process + one worker process; values are measurements, not targets"}
    srv.start()
    mem = MemSampler(srv)
    mem.start()
    try:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(args.users) as ex:
            runs = list(ex.map(lambda i: user_run(i, args, data), range(args.users)))
        result["concurrent_phase_s"] = round(time.perf_counter() - t0, 1)
        result["users"] = [r[0] for r in runs]
        clients = [r[1] for r in runs]
        uids = [c.get("/api/auth/me").json()["id"] for c in clients]
        result["jobs_seeded"] = seed_jobs(uids, args.jobs, srv.env["DATABASE_URL"])
        t0 = time.perf_counter()
        with ThreadPoolExecutor(args.users) as ex:
            list(ex.map(lambda c: c.post("/api/matching/run", json={}), clients))
            waits = list(ex.map(wait_tasks, clients))
        result["matching_all_users_s"] = round(time.perf_counter() - t0, 1)
        result["matching_failed_tasks"] = sum(len(w[1]) for w in waits)
        c = clients[0]
        lat = {}
        for name, path in (("contacts_page", "/api/contacts?page=40&page_size=50"), ("contacts_search", "/api/contacts?q=engineer&page_size=50"), ("prospects_page", "/api/prospects?page=30&page_size=50"),
                           ("prospects_filtered", "/api/prospects?min_score=40&role_category=engineer&page_size=50"), ("jobs_search", "/api/jobs?q=python&page_size=50"),
                           ("opportunities_page", "/api/opportunities?page=3&page_size=25"), ("companies", "/api/companies"), ("dashboard", "/api/dashboard"), ("email_contacts", "/api/email-contacts?page=20&page_size=50")):
            xs = [timed(c.get, path)[1] for _ in range(25)]
            lat[name] = {"p50_ms": pct(xs, 0.5), "p95_ms": pct(xs, 0.95), "max_ms": pct(xs, 1.0)}
        result["latency"] = lat
        ex_ = {}
        for name, path in (("prospects_csv", "/api/exports/prospects.csv"), ("prospects_xlsx", "/api/exports/prospects.xlsx"), ("all_data_json", "/api/me/export")):
            r, t = timed(c.get, path)
            ex_[name] = {"seconds": round(t, 2), "bytes": len(r.content), "status": r.status_code}
        result["exports"] = ex_
        job = c.get("/api/jobs?page_size=1").json()["items"][0]["id"]
        r, t = timed(c.post, "/api/tailoring", json={"job_id": job})
        result["tailoring_one_resume_s"] = {"seconds": round(t, 2), "status": r.status_code}
        result["total_rows_seen"] = {"contacts": c.get("/api/contacts").json()["total"], "prospects": c.get("/api/prospects").json()["total"], "jobs": c.get("/api/jobs").json()["total"]}
        result["peak_memory_mb_api_plus_worker"] = round(mem.peak / 2**20)
        # isolation under load: every user sees only their own contacts although companies and people overlap
        result["isolation_check"] = all(cl.get("/api/contacts").json()["total"] == args.linkedin for cl in clients)
    finally:
        mem.stop_ = True
        srv.stop()
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
