# INCOSE Requirements Assistant

This app reads a list of engineering requirements and checks each one against seven INCOSE quality criteria (A2, A3, A4, A5, A6, A9, A10). It uses Claude to do the checking. A reviewer can then accept or fix each problem it finds and download a corrected Word document.

This README explains **how to put the app online using Render**. Render is a hosting service. It takes the code from GitHub, builds it, and gives you a web address anyone can open.

> ⚠️ **Warning:** the text people upload gets sent to Anthropic for analysis. Do not upload anything sensitive, proprietary, export-controlled, or classified.

---

## Before you start

You need three things:

1. **A GitHub account** — this is where the code lives.
2. **A Render account** — sign up free at https://render.com and connect it to GitHub.
3. **An Anthropic API key with credit on it** — this is what pays for the analysis.

The API key is yours. Every analysis anyone runs on your site is charged to your account, so keep the key private.

---

## Step 1 — Put the code in your own GitHub account

Open this repository on GitHub and click **Fork**. That makes your own copy.

Do this even if you have access to the original. Render needs to read the code, and if you use someone else's copy they could change or delete it without telling you.

---

## Step 2 — Get an Anthropic API key

1. Go to https://console.anthropic.com and make an account.
2. Click **API Keys**, then **Create Key**.
3. Copy the key. It starts with `sk-ant-`. Save it somewhere safe — the site will not show it to you again.
4. Go to **Settings → Billing** and add credit. $5 is enough to try it out.

While you are there, set a **monthly spending limit**. The app has no way to stop people using it too much, so this limit is your safety net.

---

## Step 3 — Create the service on Render

In Render, click **New +**, then **Web Service**. Pick your forked repository.

Now fill in the form. Most of it you can leave alone. These are the boxes that matter:

| Box | What to put in it |
|---|---|
| **Name** | `incose-analyzer`, or any name you like. This becomes your web address, so it has to be unique. If the name is taken, add a number. |
| **Language** | **Python 3**. Not Node, not Docker. |
| **Branch** | `main` |
| **Region** | Whichever one is closest to the people who will use it. You cannot change this later. |
| **Root Directory** | Leave this **empty**. |
| **Instance Type** | `Free` is fine for testing. See the note about the free plan below. |

Then find the two command boxes and paste these in exactly:

**Build Command**

```
pip install -r backend/requirements.txt && cd frontend && npm install && npx vite build
```

**Start Command**

```
cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
```

> These two commands must match what is in the repository. If you ever change the folder layout, change these too. Getting them out of step is the single most common reason a deploy breaks.

---

## Step 4 — Add the settings

Still on the same page, find the **Environment Variables** section. Add each of these. Click "Add Environment Variable" for each new one.

| Name | Value | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | your `sk-ant-...` key | Pays for the analysis. Required. |
| `ACCESS_CODE` | a password you invent, like `orion-review-2026` | Stops strangers from using your site and spending your money. **Do not skip this.** |
| `AI_PROVIDER` | `anthropic` | Tells the app to use Claude. |
| `PYTHON_VERSION` | `3.12` | Which Python to use. |
| `NODE_VERSION` | `20` | Which Node to use. Also makes Node available when building. |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` | Stops the build downloading 150 MB of test browsers it will never use. |
| `PYTHONUNBUFFERED` | `1` | Makes the app's messages show up in the Render log. Without it they get held in memory and you never see them. |

Now click **Create Web Service**. The first build takes about 5 minutes.

---

## Step 5 — Check that it worked

Watch the log while it builds. You are looking for these lines:

```
==> Build successful 🎉
==> Your service is live 🎉
==> Available at your primary URL https://your-name.onrender.com
```

Then do these three checks:

**1. Check the log for warnings.** If you see `WARNING: ACCESS_CODE is not set`, your site is open to anyone. Go back and add it.

**2. Open your web address.** You should see a box asking for the access code. Type the code you invented. It should let you in.

**3. Run a real test.** Upload the file `samples/sample_requirements.txt` from this repository and click **Upload & Analyze**.

You should get a message like *"Done! 8 criteria violated across 10 requirements."*

**If it says "0 criteria violated", something is wrong.** Read the next section.

---

## If something goes wrong

**It says "0 criteria violated" for every requirement**

This almost never means your requirements are perfect. It usually means every analysis failed and the app counted the failures as passes.

The usual cause is the Anthropic library updating to a version the code does not work with. Check `backend/requirements.txt` still says:

```
anthropic==0.94.0
```

with `==` and not `>=`. If someone changed it, change it back and deploy again.

**Build fails: "does not appear to be a Python project"**

Your Build Command is wrong. It should be the `pip install -r backend/requirements.txt ...` line from Step 3. This error means it is trying to install a Python package from a folder that has none.

**Build works, but the service crashes straight away**

Your Start Command is wrong. It should be the `cd backend && uvicorn ...` line from Step 3.

**"A valid access code is required"**

You typed the code wrong. After 10 wrong tries the site blocks you for 15 minutes.

**"The analysis service is not configured"**

`ANTHROPIC_API_KEY` is missing or empty in the Environment Variables.

**"Analysis failed" on everything**

Your key is fine but your Anthropic account has run out of credit. Add more at https://console.anthropic.com.

---

## Things to know

**Do not change `anthropic==0.94.0` to a newer version** without testing an analysis afterwards. Newer versions of that library reject a setting the code uses. When that happens the app does not crash — it quietly reports every requirement as clean, which is much worse than an error message.

**The free plan goes to sleep** after 15 minutes of no use. The next visitor waits about a minute for it to wake up. The app also keeps everything in memory, so a sleep in the middle of a review can lose the work. If real people are using it, pay for the cheapest plan.

**The access code is one shared password.** Everybody uses the same one. It does not track who did what and it does not limit spending. If it leaks, change it in the Environment Variables and tell your users the new one.

**To update the app**, push your changes to the `main` branch on GitHub. Render rebuilds automatically. If the build fails, the old version stays online, so your site does not go down — it just stops getting updates.

---

## Running it on your own computer (optional)

You only need this if you want to change the code. You need Python and Node.js installed.

```
python run.py
```

The first time, it installs everything and creates a file called `backend/.env`. Open that file, put your API key in it, save, and run `python run.py` again. The app opens at http://localhost:3001.

Leave `ACCESS_CODE` empty in that file and it will not ask you for a code.

---

## The research work

The rule-extraction pipeline, the evaluation testbed, and the reviewer scoring live in a separate repository called `incose-research`. None of it is needed to run this app.
