# INCOSE Requirements Assistant

Reviews engineering requirements against the **INCOSE Guide to Writing Requirements**, then lets a subject-matter expert accept, reject or rewrite each finding and export a corrected document.

Seven criteria are evaluated:

| | | | |
|---|---|---|---|
| **A2** Necessary | **A3** Appropriate | **A4** Unambiguous | **A5** Complete |
| **A6** Singular | **A9** Correct | **A10** Conforming | |

> ⚠️ **Do not upload sensitive or classified material.** Requirement and context text is transmitted to a third-party AI provider (Anthropic or OpenAI) and is subject to their data-handling policies. This is a research prototype.

The research behind the tool — the ICAIv2 rule-extraction pipeline, the n8n evaluation testbed and the reviewer-reliability scoring — lives in a separate repository, **`incose-research`**.

---

## For reviewers

**You do not install anything and you do not need an API key.** You need two things from whoever runs the deployment:

1. the app's URL
2. the **access code**

Analysis runs on a single key held by the operator, so cost and provider are their concern, not yours.

### Using it

1. **Enter the access code.** The first screen is *Access Code Required*. The code is remembered for the browser tab, so navigating and refreshing will not ask again — closing the tab will.

2. **Upload requirements.** A `.txt` file, one requirement per line. All three of these parse:

   ```
   REQ-001: The system shall display GPS coordinates within 1 second.
   1. The system shall display GPS coordinates within 1 second.
   MR-C1.1: The system shall identify targets using EO/IR sensor data.
   ```

3. **Upload context** (optional, strongly recommended). A `.txt` file describing the system. Several criteria — A2 *Necessary* and A9 *Correct* in particular — ask whether a requirement traces to a stated need, and without context the model has nothing to trace to, so it over-flags.

   ```
   This system is an autonomous UAS designed for surveillance and
   reconnaissance operating at altitudes up to 40,000 feet.
   ```

4. **Click Upload & Analyze.** Roughly 15–60 seconds for ten requirements. If the operator configured more than one provider you will see a model selector; with one provider there is nothing to choose and no selector appears.

5. **Click Review Solo.**

6. **Review each finding.** Every flagged requirement lists the criteria it violates. Per violation:
   - **Accept** — take the suggested fix
   - **Reject** — keep the original wording
   - **Modify** — write your own correction

   Then **Submit All Feedback**.

7. **Export.** The *Analysis Complete* page offers **Download Report (.docx)** — the corrected document — and **Download Feedback (.json)** — your decisions, which is the file the research pipeline consumes.

> The *Set Up Multi-Reviewer* button on the same screen leads to an incomplete
> feature. Use *Review Solo*.

---

## Deploying your own instance

This section is the handover guide: everything needed to take this repository and stand up a production URL on your own Render account, owned and paid for by you.

### What you are taking on

| | |
|---|---|
| **A Render account** | The free tier works. It sleeps after 15 minutes idle, and the first request after that takes ~50 s to wake. Because sessions are held in memory, a sleep mid-review loses server-side state. For anything with real users, the cheapest paid instance avoids both problems. |
| **An AI provider account** | Analysis is billed to **your** key. Budget a few dollars for a pilot — roughly one model call per requirement. |
| **The access code** | You choose it and distribute it. It is the only thing stopping a stranger who finds the URL from spending your credits. |

You will get a **new URL** (`https://<service-name>.onrender.com`). The previous owner's URL belongs to their workspace and stops working when they delete their service, so every reviewer has to be given the new address. If keeping the existing URL matters, see [Transferring the existing service](#transferring-the-existing-service-instead) instead of deploying fresh.

### Step 1 — Get the code onto an account you control

Either fork this repository, or have it transferred to you on GitHub. Render needs to read it, so a fork you own is the simplest arrangement. Deploying from someone else's repository works, but you cannot merge changes and the original owner can delete it out from under you.

### Step 2 — Get an API key

Anthropic is the default and the better-tested path.

1. Create an account at **https://console.anthropic.com**
2. **API Keys → Create Key**, copy the value (it starts with `sk-ant-`)
3. Add credit under **Settings → Billing** — $5 is plenty to start
4. Consider setting a monthly spend limit on the same page. The access code does not cap usage, so a provider-side limit is your real backstop.

OpenAI is optional. Supplying a second key only adds a model selector to the UI.

### Step 3 — Create the Render service

There are two routes. **The Blueprint route is recommended** — it reads [`render.yaml`](render.yaml) from the repository, so the build and start commands cannot drift out of step with the code, which is a failure this project has already hit once.

#### Route A — Blueprint (recommended)

1. In Render: **New + → Blueprint**
2. Connect your GitHub account and pick the repository
3. Render reads `render.yaml` and shows a service named `incose-analyzer`
4. It will prompt for the three values marked `sync: false` — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ACCESS_CODE`. Fill in the first and third; leave `OPENAI_API_KEY` blank unless you have one.
5. **Apply**

Everything else — build command, start command, Python and Node versions — comes from the file. Skip to Step 5.

#### Route B — Web Service by hand

**New + → Web Service**, then fill the form. Field names shift occasionally as Render updates its UI; match on meaning where the wording differs.

| Field | Value | Notes |
|---|---|---|
| **Source Code** | Your fork of this repository | Connect the GitHub account that owns it |
| **Name** | `incose-analyzer` | Becomes the URL: `https://incose-analyzer.onrender.com`. Must be globally unique, so expect to add a suffix. |
| **Project** | *(optional)* | Organisational only |
| **Language** | `Python 3` | Not Node, and not Docker — the Python runtime installs Node as well once `NODE_VERSION` is set |
| **Branch** | `main` | |
| **Region** | Nearest your reviewers | Cannot be changed later without recreating the service |
| **Root Directory** | *(leave blank)* | The app is at the repository root |
| **Build Command** | `pip install -e .[app] && cd frontend && npm install && npx vite build` | Installs the Python package, then builds the React bundle the backend serves |
| **Start Command** | `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT` | `$PORT` is supplied by Render; do not hard-code it |
| **Instance Type** | `Free` to trial, `Starter` for real use | See the sleep caveat above |
| **Environment Variables** | See Step 4 | |

Under **Advanced**:

| Field | Value | Notes |
|---|---|---|
| **Health Check Path** | `/api` | Returns JSON and is exempt from the access code, so the check passes without one. Do not use `/` — it serves `index.html` and would report healthy even if the API were broken. |
| **Auto-Deploy** | `Yes` | Redeploys on every push to `main` |
| **Pre-Deploy Command** | *(blank)* | |
| **Persistent Disk** | *(none)* | Nothing is written to disk |

### Step 4 — Environment variables

Set these under **Environment**. The three secrets go in the dashboard only — never commit them.

| Key | Value | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | your `sk-ant-…` key | **Yes** (unless you use OpenAI instead) |
| `ACCESS_CODE` | a phrase you invent, e.g. `orion-review-2026` | **Yes in production.** Without it the URL is open to anyone. |
| `AI_PROVIDER` | `anthropic` | Yes — must name a provider you supplied a key for |
| `PYTHONUNBUFFERED` | `1` | Yes. Python block-buffers stdout when it is a pipe, which is what Render gives it; without this the startup warnings never reach your log. |
| `PYTHON_VERSION` | `3.12` | Yes |
| `NODE_VERSION` | `20` | Yes — this is also what makes Node available during the build |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` | Yes. The build runs a plain `npm install`; without this it pulls ~150 MB of browsers the server never uses. |
| `OPENAI_API_KEY` | your `sk-…` key | Optional — adds GPT-4o to the model selector |

Changing any variable triggers a redeploy.

### Step 5 — Verify the first deploy

The build takes 3–6 minutes. Watch the log for:

```
==> Running build command 'pip install -e .[app] && cd frontend && ...'
==> Build successful 🎉
==> Deploying...
==> Your service is live 🎉
```

Then check three things:

1. **No startup warnings.** A correctly configured service logs nothing at startup. If you see `WARNING: ACCESS_CODE is not set` or `WARNING: no AI provider key configured`, fix the variable and redeploy — the first means your URL is open and billing to you.
2. **`https://<your-service>.onrender.com/api/config`** returns JSON with `"ready": true` and `"auth_required": true`. `ready: false` means no key was found; `auth_required: false` means no access code.
3. **Open the URL.** You should get the *Access Code Required* screen, and your code should let you through to *Upload Requirements*.

Run one small requirements file end to end before handing the URL out — `data/samples/sample_requirements.txt` is in the repository for exactly this.

### Step 6 — Hand it out

Reviewers need the URL and the access code, nothing else. They install nothing and never see a key.

### Ongoing ownership

**Updating the app.** Push to `main`; with Auto-Deploy on, Render rebuilds. Watch the log — a build failure leaves the previous version running, so the site stays up but stops reflecting your changes.

**Rotating the access code.** Change `ACCESS_CODE` in the dashboard, wait for the redeploy, and tell the reviewers. Anyone mid-session is logged out.

**Rotating the API key.** Revoke it in the provider console, create a new one, update the variable. Do it in that order if you think the key leaked.

**Watching cost.** Render shows service hours; the provider console shows token spend. There is nothing in the app that caps either — set the limit on the provider side.

**If a service is misbehaving** and the logs are not enough, **Manual Deploy → Clear build cache & deploy** rules out a stale cache, which is the usual cause of "it works locally but not on Render".

### Transferring the existing service instead

If you would rather keep the current URL than issue a new one, Render can move a service between workspaces rather than recreating it. The outgoing owner starts the transfer from the service's own **Settings** page and you accept; the URL, environment variables and deploy history come with it. (Render moves this control around between UI revisions — if it is not under Settings, search their docs for "transfer service".)

Two things to handle immediately after a transfer: **rotate `ANTHROPIC_API_KEY` to your own key** (the transferred variable still holds the previous owner's, and their billing), and repoint the service at your fork under **Settings → Build & Deploy → Repository** if you took ownership of the code as well.

### What the access code does and does not do

It is one shared secret with per-IP lockout after 10 failed attempts. It stops casual discovery of the URL. It does **not** attribute usage to individual reviewers or cap spend, so a leaked code means anyone holding it can burn credits until you rotate it. For a known reviewer group that trade is usually fine; for wider distribution, add a spend limit on the provider key.

### Session storage

Sessions are held **in memory only** — nothing a reviewer uploads or generates is written to disk. A restart therefore drops server-side state, though the client can restore a session it still has open. On the free tier, which sleeps idle instances, expect long-running reviews to need that restore.

---

## For developers — running locally

**Prerequisites:** Python 3.10+ and Node.js 20+.

```bash
git clone https://github.com/packers12345/incose-assistant-app.git
cd incose-assistant-app
python run.py
```

`run.py` installs both dependency sets on first run, creates `backend/.env` from the template, and stops to tell you to fill in a key. Add it:

```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Then run `python run.py` again. It starts the backend on **8000**, the Vite dev server on **3001**, and opens a browser. `Ctrl+C` stops both.

Leave `ACCESS_CODE` empty locally and the gate is transparent.

### Layout

```
backend/     FastAPI app: analysis, feedback, document export
frontend/    React SPA (Vite); built to frontend/dist and served by the backend
shared/      the evaluator and the INCOSE rubric it loads
data/samples/  example requirement and context files
```

`shared/` is deliberately narrow — `evaluator.py` plus `rubrics/incose_rules.json`. It is installed as a package (`pip install -e .[app]`) so `backend/main.py` can import it regardless of the working directory it is launched from. The research repository carries a fuller version of the same package.

### Dependencies

All declared in [`pyproject.toml`](pyproject.toml), so the app and the research components cannot drift onto different library versions. `backend/requirements.txt` is a one-line shim that forwards to it, and **must be run from the repository root** — pip resolves a relative path inside a requirements file against the current working directory, not against the file's own location.

### Browser tests

Playwright drives the real built frontend served by the backend, which is the only way to catch the browser-only failures — missing request headers, downloads, client-side routing on a hard refresh.

```bash
cd frontend && npm install && npx playwright install chromium
cd ../backend && python -m uvicorn main:app --port 8153     # separate terminal
cd ../frontend && E2E_ACCESS_CODE=<code> npx playwright test
```

The full-flow test makes real model calls, so it costs a little and needs a working key in `backend/.env`.

---

## Troubleshooting

**Build fails: `does not appear to be a Python project`**
The build command ran `pip install -r backend/requirements.txt` from somewhere other than the repository root, so the `-e .` inside it resolved to the wrong directory. Use `pip install -e .[app]` as the build command.

**Deploy succeeds, then the service crashes on start**
The start command is probably still pointing at an old path. It must be `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`.

**"A valid access code is required"**
The code is wrong, or was rotated. After 10 failures from one IP the endpoint locks out for 15 minutes.

**Reviewers see "The analysis service is not configured"**
No provider key is set on the server. `/api/config` reports zero available providers. Set `ANTHROPIC_API_KEY` in the Render dashboard.

**"Analysis failed" on every requirement**
The key is valid but the account is out of credit. Check billing at console.anthropic.com or platform.openai.com.

**`python is not recognized`** (local)
Python is not on PATH. Reinstall from python.org and tick **Add Python to PATH** on the first installer screen.

**`running scripts is disabled on this system`** (local, Windows)
Run once in PowerShell, then retry:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Analysis is slow**
Expected — one model call per requirement, issued in parallel. Ten requirements take 15–30 seconds; fifty may take a few minutes.
