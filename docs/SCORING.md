# Scoring methodology

Every score in ReferralOS is **explainable, reproducible and separate from confidence**. No score is produced by a language model.
Each stored score keeps its **version string**, a **snapshot of the configuration** (weights, policy) and the **inputs**, so it can be recomputed exactly
(`tests/test_scoring.py::test_scoring_runs_after_import_and_is_reproducible` does this from the stored row).

Weights are always rescaled to total exactly 100 when saved; a weight set with a missing component, a negative value or a zero total is rejected.

## Missing-data policy (one policy, applied in one place)

Missing data is **unknown, never negative**. A component with no usable data is marked `known: false` and handled by the user's policy
(Settings → Scoring), implemented once in `services/scoring.py::combine`:

| Policy | Effect on the score | Effect on confidence |
|---|---|---|
| `neutral` (default) | the component counts as **half of its weight** | lowered |
| `exclude` | the component is dropped and the remaining weights are renormalised to 100 | lowered |

An *observed* fact is different from an unknown: "this company is not on your target list" scores low (0.2) because we know it; "you have not set target companies" is unknown.

## 1. General Referral Priority Score (`referral-priority/1`, 0-100) — who is worth approaching

| Component | Weight | How the 0-1 value is derived (only from supplied facts) |
|---|---|---|
| Company relevance | 25 | target company 1.0; not a target (when targets exist) 0.2; excluded company 0 (and the person is never tiered); no targets set → unknown |
| Potential referral capability | 25 | by classified role: engineering manager .8, engineer .7, recruiter .6, leadership .5, product .5, other .3; ×0.6 when the connection is old (employer may be stale); unknown role/company → unknown. *Potential only: nobody is assumed able to refer.* |
| Technical / role relevance | 20 | overlap between the contact's title domains (backend, ML, data, platform, …) and your target roles/skills; technical recruiters .8; needs your targets to compare |
| Seniority & organisational context | 10 | intern .3, junior .6, mid .8, senior .9, staff/principal .8, manager .8, director+ .5 (**seniority is not referral ability**; this only reflects how typical a referrer is) |
| Approachability & relationship | 10 | connection recency (≤1y 1.0, ≤3y .7, else .5); 1.0 if the company is a past employer listed in *your* profile. Nothing else is assumed. |
| Hiring relevance | 10 | recruiter 1.0, eng. manager .9, leadership .6, engineer .5, product .3; +0.3 when the company has verified open roles |

**Confidence (0-100), shown separately and never presented as a probability of a referral:** completeness of known components 35 · source reliability (company, title, profile URL present) 20 ·
freshness of the connection 20 · consistency (an old connection halves it) 10 · verified-vs-inferred (we never verify employment ourselves; only you can) 15.

**Employment status** is *inferred* from the connection date only (LinkedIn exports carry no employment dates): ≤ 2 years `likely_current`, ≥ 5 years (configurable) `possibly_outdated`,
otherwise `unknown`; `verified` exists only when the user marks it.

**Tiers** default 100 / 400 / 500 (configurable, 1-6 tiers). Ranking order: higher score, then higher confidence, then more recent connection, then name, then id (deterministic; shuffling the input
does not change the result). Each person is in exactly one tier; excluded companies are never tiered.

## 2. Job Match Score (`job-match/1`, 0-100) — how well a job fits your profile

| Component | Weight | Derivation |
|---|---|---|
| Technical skill alignment | 35 | weighted mean over the skills the posting names (mandatory ×2, preferred ×1) of: strong evidence 1.0, partial .5, needs verification .4, conflicting .2, no evidence 0 |
| Required qualification alignment | 25 | the same mapping over mandatory requirements (skills, years of experience, degree) |
| Role / career alignment | 15 | similarity of the job title to your target roles (≥80% → 1.0 … <40% → .1), ×0.4 if the employment type is not one you want |
| Experience & project alignment | 15 | share of the posting's named skills that appear in your jobs or projects |
| Location / arrangement | 10 | from the location eligibility check; ×0.5 if the arrangement is not one you prefer |

The **requirement matrix** maps every important requirement to the profile facts that support it, with a status and an explanation:
`STRONG_EVIDENCE` (used at a job or in a project), `PARTIAL_EVIDENCE` (studied; a related skill in the same family; part of the required experience),
`NEEDS_VERIFICATION` (listed but nothing shows its use; only a GitHub/portfolio suggestion), `CONFLICTING_EVIDENCE` (a supporting entry has an unresolved conflict),
`NO_EVIDENCE` ("nothing in your profile shows this — absence of evidence, not proof you lack it"). A "3+ years of Python" requirement is measured against your *Python* experience, not your whole career.
Skill synonyms are normalised ("Postgres" = PostgreSQL, "k8s" = Kubernetes).

**Eligibility** (graduation year, degree level, minimum experience, work authorisation, citizenship, clearance, location) is judged **separately from the score** as
`SATISFIED` / `VIOLATED` / `UNCERTAIN`, each with a reason and, for uncertain items, a review action. Missing data → `UNCERTAIN`; a profile fact is never altered to satisfy a constraint.
`prioritize_applying` is `no` if anything is violated, `review` if anything is uncertain or the job is not verified open, otherwise `yes` (score ≥ 60) or `maybe`.

## 3. Job-specific contact score (`job-contact/1`, 0-100) — who to ask first for *this* job

Employment at the company 25 (verified by you 1.0 · likely current .6 · possibly outdated .25 · unknown → unknown) · relevant role 25 (technical recruiter 1.0; engineer with a domain overlap 1.0;
engineer .8; manager .9; leadership .5; product .3) · domain alignment 20 · seniority 10 · relationship 10 · confidence 10 (the general confidence above).
The top **1-5 per job (default 3)** are recommended; a person who fits several jobs at one company is linked across them (`also_fits_jobs`) so they receive **one** consolidated message.
Company membership, seniority or a public profile is never treated as proof that someone can submit a referral, and every explanation says so.
*Shortcut:* scores are computed for the 40 best general-ranked contacts per company, and the top 10 per job are stored.

## 4. Opportunity Priority Score (`opportunity/1`, 0-100) and ordering

Match 35 · verification confidence 20 (verified 1.0, unconfirmed .5, unknown .25, possibly closed .1, closed 0; ×0.8 when the evidence is stale) · contact quality 20 (best contact's score; HR-CSV contacts only → .3;
nobody known → 0, because that is a known fact) · deadline urgency 10 (≤14 days 1.0, ≤30 days .6, later .3, passed 0, none → unknown) · eligibility 15 (all satisfied 1.0, any uncertain .5, any violated 0).

**An uncertain job with a high match must not silently outrank a verified, eligible opening.** Display order is therefore `(readiness group, score)`:
0 verified and eligible → 1 verified, eligibility to confirm → 2 not yet verified → 3 open but you appear ineligible → 4 closed or likely closed.
Each card also shows `score_only_rank` and a plain-language trade-off ("Ranked below … despite a higher score because …") whenever the two orders differ.

## 5. Resume Match Score (`resume-match/1`, 0-100)

Technical skills 30 · relevant experience & projects 30 · mandatory qualification coverage 20 · responsibilities alignment 10 · natural keyword coverage & readability 10.
It is an **internal alignment estimate**, labelled as such everywhere: *not an ATS score, no prediction of passing screening.* Suggestions only name things the profile could support
("if you have used X, add where") and say plainly when nothing supports a requirement; the "estimated gain" is an approximation.
