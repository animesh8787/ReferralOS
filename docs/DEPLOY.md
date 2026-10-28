# Deploying ReferralOS: Vercel (web) + Render (API) + Supabase (database, files) + Firebase (sign-in)

Nothing here has been run against the live services; follow the steps in order and use the checks at the end. **Never paste keys into the repository or into chat**: they go only into the hosting dashboards.

## 0. Generate your encryption key (once)
```powershell
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```
Save the output as `APP_KEK`. It encrypts OAuth tokens and API keys in the database. **If you lose it, those stored tokens become unreadable; if it leaks, rotate it.**

## 1. Supabase (PostgreSQL + file storage)
1. supabase.com → New project. Save the database password.
2. **Project Settings → Database → Connect → Session pooler**. Copy the URI and change the start so it reads `postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`. This is `DATABASE_URL`. Use the **pooler**, not the direct host: Render can't reach Supabase's direct host (IPv6 only).
3. **Storage → New bucket** named `referralos`, **private** (public off).
4. **Project Settings → API**: copy the Project URL (`SUPABASE_URL`) and the **service_role** key (`SUPABASE_SERVICE_KEY`). The service key bypasses all access rules, so it lives only on Render.

## 2. Firebase (shared with Nexus OS)
Use the existing `nexus-os-87` project so one account works in both apps.
1. Authentication → Sign-in method: **Email/Password** and **Google** enabled (already on for Nexus OS).
2. Authentication → Settings → **Authorised domains**: add your Vercel domain (and a custom domain if you add one).
3. Project settings → Your apps → Web app: note `apiKey`, `authDomain`, `projectId`, `appId`. These are public identifiers.
4. Optional: Authentication → Templates → customise the verification and password-reset emails.

## 3. Render (API + background worker)
1. render.com → New → **Blueprint** → connect the GitHub repo (it reads `render.yaml`), or New → Web Service → Docker with root directory `backend`.
2. Set the environment variables (`sync: false` ones are prompted):

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Supabase session-pooler URI from step 1 |
| `APP_KEK` | from step 0 |
| `APP_URL` | `https://<your-vercel-domain>` |
| `CORS_ORIGINS` | `["https://<your-vercel-domain>"]` |
| `FIREBASE_PROJECT_ID` | `nexus-os-87` |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | from step 1 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | only for sending through Gmail (step 5) |

   `ADAPTER_MODE=real`, `RUN_WORKER=1`, `COOKIE_SECURE=true` and `STORAGE_BUCKET` are already in the blueprint.
3. Deploy. The container runs `alembic upgrade head` first, then starts the API with the worker inside it. Open `https://<service>.onrender.com/api/health`: it should answer.

**Free-plan behaviour:** the service sleeps after 15 minutes without traffic; the next request takes about a minute, and background jobs (imports, scoring, sending) pause while it sleeps. For always-on behaviour use a paid instance.

## 4. Vercel (web app)
1. vercel.com → Add New → Project → the repo, **Root Directory: `frontend`**.
2. Environment variables, set **before** the first deploy (the proxy address is read at build time):

| Variable | Value |
|---|---|
| `BACKEND_URL` | `https://<service>.onrender.com` |
| `NEXT_PUBLIC_FIREBASE_API_KEY` / `_AUTH_DOMAIN` / `_PROJECT_ID` / `_APP_ID` | from Firebase step 3 |

3. Deploy, then add the Vercel domain to Firebase's authorised domains (step 2.2) and to Render's `APP_URL` / `CORS_ORIGINS`, and redeploy the API.
4. The browser only ever talks to Vercel; `/api/*` is forwarded to Render, so the session cookies are first-party.

## 5. Gmail sending (optional, only for outreach)
Sign-in does **not** need this. Sending mail through a user's Gmail does.
1. Google Cloud Console → the Nexus project (or a new one) → enable the **Gmail API** → OAuth consent screen → add the `gmail.send` scope (and `gmail.readonly` only if you keep reply tracking).
2. Credentials → OAuth client (Web): Authorised redirect URI `https://<your-vercel-domain>/settings/gmail/callback`.
3. Put the client id and secret on Render and redeploy.
4. While the consent screen is in "Testing" only the test users you add can connect. Public use of `gmail.send` needs Google's app verification (review, privacy policy, and, for sensitive scopes, a security assessment). Plan for that before telling other people to use it.

## 6. Checks after the first deploy
- Open the Vercel URL → **Continue with Google** works; the unverified banner appears for a new email/password account and the resend button sends the Firebase email.
- Upload a resume → status becomes `parsed` (this proves the worker thread, the database and Supabase Storage together).
- Upload a LinkedIn CSV of about 10 MB. If Vercel rejects the request size, upload straight to the API instead (needs CORS and a small frontend change) and tell me.
- Settings → export your data, then delete a throwaway account: its files should disappear from the Supabase bucket, and the Firebase sign-in should still exist.

## Things to know
- **Rate limits are per process** (in memory). Fine for one instance; use a shared store before running several.
- **SQLite is for local use only.** Production uses Postgres.
- **Account deletion** removes ReferralOS data only. The shared Firebase sign-in remains, so Nexus OS keeps working.
- **Secrets rotation:** the Supabase service key, `APP_KEK` and the Google client secret live only in the Render dashboard.
