# Real-service check

Run: 2026-10-27 03:07 local time · User-Agent: `ReferralOS/0.1 (personal job-search tool; honours robots.txt)` · 4 s · read-only GET requests only

| Integration | Result | Detail |
|---|---|---|
| GitHub REST (public) | OK | octocat: 8 public repos listed; 5 mapped to project suggestions |
| GitHub README fetch | OK | octocat/Spoon-Knife: 780 chars |
| greenhouse board API | OK | greenhouse: 18 jobs; first: 'Commercial Counsel' loc='Eastern Timezone' apply_url=yes desc_chars=7504 |
| lever board API | OK | lever: 0 jobs |
| ashby board API | OK | ashby: 66 jobs; first: 'Engineering Manager - EU' loc='Remote - European Union' apply_url=yes desc_chars=20167 |
| workable board API | OK | huggingface: 6 jobs; first: 'Open-Source Machine Learning Engineer - EMEA Remot' loc='Paris, Île-de-France, France' apply_url=yes desc_chars=5019 |
| smartrecruiters board API | OK | smartrecruiters: 1 jobs; first: 'Engineering Team Lead SRE' loc='Poland, Remote, pl' apply_url=yes desc_chars=0 |

Not exercised against real services (and so unverified): Gmail send/OAuth, LLM provider, SMTP (not built), LinkedIn (disabled by design).
