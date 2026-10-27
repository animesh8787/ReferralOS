"""One-shot, READ-ONLY check of the integrations that were otherwise only tested against fixtures.

It makes a handful of public GET requests (GitHub REST API; public ATS job-board APIs) with the app's honest User-Agent, through the same
adapters the product uses. It sends nothing, logs in nowhere and stores nothing. Results are written to docs/REAL_SERVICE_CHECK.md.

    cd backend && ADAPTER_MODE=real uv run python ../scripts/smoke_real.py
"""
import os
import sys
import time
from pathlib import Path

os.environ["ADAPTER_MODE"] = "real"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters import ats, github_api  # noqa: E402
from app.adapters.http import PoliteFetcher, USER_AGENT, make_client  # noqa: E402

CANDIDATES = {  # public board tokens of well-known companies; the first that answers is used, so a dead token is not a failure of the adapter
    "greenhouse": ["greenhouse", "airbnb", "stripe", "gitlab"], "lever": ["lever", "netflix", "palantir"], "ashby": ["ashby", "ramp", "notion"],
    "workable": ["workable", "huggingface"], "smartrecruiters": ["smartrecruiters", "Visa", "BoschGroup"]}


def main():
    rows, t0 = [], time.time()
    c = make_client()
    gh = github_api.GitHubClient(c)
    try:
        repos = gh.repos("octocat")
        items = github_api.to_items(repos[:5], {})
        rows.append(("GitHub REST (public)", "OK", f"octocat: {len(repos)} public repos listed; {sum(1 for i in items if i.section == 'project')} mapped to project suggestions"))
        rd = gh.readme(repos[0]["full_name"])
        rows.append(("GitHub README fetch", "OK" if rd is not None else "no README", f"{repos[0]['full_name']}: {len(rd or '')} chars"))
    except Exception as e:  # noqa: BLE001
        rows.append(("GitHub REST (public)", "FAILED", f"{type(e).__name__}: {e}"))
    f = PoliteFetcher(c, respect_robots=False)
    for name, tokens in CANDIDATES.items():
        done = False
        for tok in tokens:
            try:
                jobs = ats.list_jobs(f, name, tok)
            except ats.BoardNotFound:
                continue
            except Exception as e:  # noqa: BLE001
                rows.append((f"{name} board API", "FAILED", f"{tok}: {type(e).__name__}: {str(e)[:100]}"))
                done = True
                break
            sample = jobs[0] if jobs else None
            ok = bool(sample and sample.title and sample.source_job_id)
            rows.append((f"{name} board API", "OK" if ok or not jobs else "SHAPE?", f"{tok}: {len(jobs)} jobs" + (f"; first: '{sample.title[:50]}' loc={sample.location!r} apply_url={'yes' if sample.apply_url else 'NO'} desc_chars={len(sample.description)}" if sample else "")))
            done = True
            break
        if not done:
            rows.append((f"{name} board API", "NO BOARD FOUND", f"none of {tokens} answered (tokens change; this says nothing about the adapter)"))
    md = ["# Real-service check", "", f"Run: {time.strftime('%Y-%m-%d %H:%M')} local time · User-Agent: `{USER_AGENT}` · {int(time.time() - t0)} s · read-only GET requests only", "",
          "| Integration | Result | Detail |", "|---|---|---|"] + [f"| {a} | {b} | {d} |" for a, b, d in rows]
    md += ["", "Not exercised against real services (and so unverified): Gmail send/OAuth, LLM provider, SMTP (not built), LinkedIn (disabled by design)."]
    (ROOT / "docs/REAL_SERVICE_CHECK.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
