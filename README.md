# INCOSE Requirements Assistant

Reviews engineering requirements against the **INCOSE Guide to Writing Requirements**, then lets one or more subject-matter experts accept, reject or rewrite each finding and export a corrected document.

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

5. **Choose a path.** *Review Solo* to work alone, or *Set Up Multi-Reviewer* to invite others.

6. **Review each finding.** Every flagged requirement lists the criteria it violates. Per violation:
   - **Accept** — take the suggested fix
   - **Reject** — keep the original wording
   - **Modify** — write your own correction

   Then **Submit All Feedback**.

7. **Export.** The *Analysis Complete* page offers **Download Report (.docx)** — the corrected document — and **Download Feedback (.json)** — your decisions, which is the file the research pipeline consumes.

### Multi-reviewer

From *Multi-Reviewer Setup*, add reviewers and invite them. Each gets their own review link and works independently; the **Consensus Dashboard** shows where they agreed, where they split, and lets you resolve or override each disagreement.

Invited reviewers need the same access code. They do not need a key.

---

## For the operator — deploying

Hosted on [Render](https://render.com) as a single web service. FastAPI serves both the API and the built React bundle, so there is no separate static site.

**Build command**

```bash
pip install -e .[app] && cd frontend && npm install && npx vite build
```

**Start command**

```bash
cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
```

> These are also in [`render.yaml`](render.yaml), but Render only applies that file automatically to Blueprint-managed services. A service created by hand uses whatever is in its dashboard, so if you created it that way, set both there and keep them in step with the file.

**Environment variables** — set the secrets in the dashboard (Environment tab), never in the repo:

| Variable | Required | Purpose |
|---|---|---|
| `ACCESS_CODE` | **yes, in production** | The shared code you hand to reviewers. Without it the URL is open to anyone who finds it, spending your credits. |
| `ANTHROPIC_API_KEY` | one key required | Analysis runs on this. |
| `OPENAI_API_KEY` | optional | Supplying it adds GPT-4o to the model selector; omit it and the UI offers only Claude. |
| `AI_PROVIDER` | `anthropic` | Which provider the app opens on. Must be one you supplied a key for. |
| `PYTHONUNBUFFERED` | `1` | Python block-buffers stdout when it is a pipe, which is what Render gives it. The startup warnings below are `print()` calls and never reach the log without this. |
| `PYTHON_VERSION` | `3.12` | |
| `NODE_VERSION` | `20` | |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` | The build runs a plain `npm install` (vite is itself a dev dependency, so `--omit=dev` is not an option), which would otherwise pull ~150 MB of browsers the server never uses. |

At startup the server warns if `ACCESS_CODE` is unset or if no provider key is configured. Check the Render log after the first deploy — a deployment that boots cleanly but silently serves an open, paid endpoint is the failure worth catching early.

### What the access code does and does not do

It is one shared secret with per-IP lockout after 10 failed attempts. It stops casual discovery of the URL. It does **not** attribute usage to individual reviewers or cap spend, so a leaked code means anyone holding it can burn credits until you rotate it. For a known reviewer group that trade is usually fine; for wider distribution, add a spend limit on the provider key.

### Session storage

Sessions are held **in memory only** — nothing a reviewer uploads or generates is written to disk. A restart therefore drops server-side state, though the client can restore a session it still has open. On Render's free tier, which sleeps idle instances, expect long-running reviews to need that restore.

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
backend/     FastAPI app: analysis, feedback, consensus, document export
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
