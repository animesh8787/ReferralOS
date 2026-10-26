"""Generates LARGE synthetic datasets for performance/scale runs into ./synthetic_out (gitignored). Run from the repo root:
    cd backend && uv run python ../scripts/gen_synthetic.py --linkedin 11000 --hr 5000 --jobs 500 --users 3
Every record is flagged synthetic by construction: invented names, 'synthetic-' LinkedIn slugs, reserved example domains."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tests import synth_contacts as sc  # noqa: E402

TITLES = ["Backend Engineer", "Platform Engineer", "Data Engineer", "Machine Learning Engineer", "DevOps Engineer", "Software Engineering Intern", "Frontend Engineer", "SRE"]
SKILLS = ["Python", "PostgreSQL", "Docker", "Kubernetes", "AWS", "Redis", "Kafka", "Spark", "React", "Go", "Terraform", "PyTorch"]


def jobs(n: int):
    for i in range(n):
        co = sc.COMPANIES[i % len(sc.COMPANIES)]
        req = [SKILLS[(i + k) % len(SKILLS)] for k in range(3)]
        yield {"id": f"syn-{i:04d}", "company": co, "title": TITLES[i % len(TITLES)] + (f" {i // len(TITLES)}" if i >= len(TITLES) else ""), "location": ["Remote", "Austin, TX", "Berlin"][i % 3],
               "description": "Requirements:\n" + "\n".join(f"- Experience with {s}" for s in req) + "\n\nNice to have:\n- " + SKILLS[(i + 5) % len(SKILLS)] + " experience\n\nResponsibilities:\n- Build and run services\n" + "x" * 40}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--linkedin", type=int, default=11000)
    ap.add_argument("--hr", type=int, default=5000)
    ap.add_argument("--jobs", type=int, default=500)
    ap.add_argument("--users", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "synthetic_out"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for u in range(a.users):  # overlapping companies across users on purpose: tenant isolation must hold
        start = u * 3000
        (out / f"user{u}_linkedin.csv").write_bytes(sc.to_csv(sc.LI_HEADER, sc.li_rows(a.linkedin, start=start)))
        (out / f"user{u}_hr.csv").write_bytes(sc.to_csv(sc.HR_HEADER, sc.hr_rows(a.hr, start=start)))
    (out / "jobs.json").write_text(json.dumps(list(jobs(a.jobs)), indent=1), encoding="utf-8")
    print(f"wrote {a.users} users x ({a.linkedin} LinkedIn + {a.hr} HR rows) and {a.jobs} jobs to {out}")


if __name__ == "__main__":
    main()
