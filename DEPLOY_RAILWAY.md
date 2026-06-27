# Deploying the CV Screener to Railway

This gets the tool live on a public `https://...` URL so your HR team can use it and
your Meta hiring ad can link to it. No laptop needs to stay on. ~15–20 minutes.

Cost: roughly $5–10/month (Railway's usage-based pricing) + your Claude API usage.

---

## What you need before starting
1. A **GitHub account** (free) — github.com
2. A **Railway account** (free to start) — railway.app  (sign up with GitHub)
3. Your **Anthropic API key** — console.anthropic.com → API Keys → Create Key
   (starts with `sk-ant-`)

---

## Step 1 — Put the code on GitHub
Railway deploys from a GitHub repository.

Easiest path (no command line):
1. Go to github.com → click **New repository** → name it `cv-screener` → **Private** →
   Create.
2. On the new repo page, click **uploading an existing file**.
3. Unzip `cv-screener.zip` on your computer, then drag **all the files inside the
   `cv-screener` folder** into the GitHub upload area. (Upload the contents — the
   `main.py`, `services/` folder, etc. — not the outer zip.)
4. Click **Commit changes**.

> The `.gitignore` we included keeps your local database, uploaded CVs, and secrets
> out of GitHub automatically. Never upload a `.env` file.

---

## Step 2 — Create the Railway project
1. Go to railway.app → **New Project** → **Deploy from GitHub repo**.
2. Authorize Railway to see your GitHub, then pick the `cv-screener` repo.
3. Railway auto-detects Python and starts building. Wait for the first build to finish
   (it will likely succeed but the app won't fully work until Step 3 + 4).

---

## Step 3 — Add the API key (and other settings)
In your Railway project → click the service → **Variables** tab → **New Variable**.
Add these one by one:

| Variable            | Value                                  |
|---------------------|----------------------------------------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` (your key)                |
| `UPLOAD_DIR`        | `/data/uploads`                        |
| `DATABASE_URL`      | `sqlite:////data/cv_screener.db`       |

(Optional, only if you use Meta lead pull later: `META_ACCESS_TOKEN`.)

> Note the **four** slashes in the DATABASE_URL — `sqlite:////data/...` — that means an
> absolute path. This points your database at the persistent volume in the next step.

---

## Step 4 — Add a persistent volume (CRITICAL — don't skip)
Without this, your candidate database and uploaded CVs are **wiped on every redeploy**.

1. In the service → **Settings** (or the **Volumes** section) → **New Volume**.
2. Set the **Mount path** to: `/data`
3. Save. Railway will redeploy with the volume attached.

Now both the database (`/data/cv_screener.db`) and CVs (`/data/uploads`) live on
storage that survives restarts and redeploys.

---

## Step 5 — Get your public URL
1. Service → **Settings** → **Networking** → **Generate Domain**.
2. Railway gives you something like `https://cv-screener-production.up.railway.app`.

Test it:
- `https://YOUR-URL/docs` → the built-in control panel (create jobs, upload CVs, see scores)
- After you create a job, `https://YOUR-URL/apply/1` → the public Parakkat application page

---

## Step 6 — Point your Meta ad at it
When you run a Meta hiring ad, set the destination/link URL to:
```
https://YOUR-URL/apply/<job_id>
```
Replace `<job_id>` with the ID shown when you created the job in `/docs`. Applicants
land on the branded page, submit their CV, and it flows straight into screening tagged
as `meta_ads`.

---

## Day-to-day use
- **Create a job:** go to `/docs`, find `POST /jobs`, click "Try it out", fill the
  fields (title, description, required_skills, budget band optional), Execute. Note the
  returned `id`.
- **Upload CVs manually:** `POST /upload` in `/docs`, pick the job_id, attach files.
- **See results:** `GET /candidates?job_id=...` — scores, salary, recommendation.
- **Download a CV:** `GET /candidates/{id}/download`.
- **Export shortlist:** `GET /export?job_id=...` returns a CSV.

For a nicer interface than `/docs`, the React dashboard (`frontend/Dashboard.jsx`) can be
deployed separately to Vercel later — point its `VITE_API_URL` at your Railway URL. Not
required to start.

---

## Updating the app later
Any change you commit to the GitHub repo triggers Railway to rebuild and redeploy
automatically. Your `/data` volume (database + CVs) is untouched by redeploys.

---

## Troubleshooting
- **Build fails:** check the **Deploy logs** in Railway. Most often a typo in a variable.
- **CVs score as `error`:** the `ANTHROPIC_API_KEY` is missing or wrong. Re-check Step 3.
- **Data disappeared after a deploy:** the volume (Step 4) wasn't added or the
  `DATABASE_URL`/`UPLOAD_DIR` don't point at `/data`. Fix the variables and volume.
- **Applicants can't reach the page:** make sure you generated a domain (Step 5).

---

## A note on scale
This runs Claude evaluations as in-process background tasks. That's fine for steady
applicant flow. If a single Meta campaign dumps 100+ CVs in an hour, evaluations queue
on the web process and may slow the UI. When you hit that volume, the next upgrade is a
proper job queue (Redis + a worker service — Railway supports adding a Redis service and
a second worker process). Ask for that when you're ready.
