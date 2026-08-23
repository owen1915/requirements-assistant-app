# INCOSE Requirements Assistant

Automatically reviews engineering requirements against the **INCOSE Guide to Writing Requirements** (A2–A10 criteria). Upload a requirements document, get a detailed violation report, review each finding, and export a corrected Word document.

Works with **Anthropic (Claude)** or **OpenAI (GPT-4o)**.

---

> ⚠️ **IMPORTANT — Do not enter sensitive or classified data.** This is a prototype tool. Do not upload requirements, context files, or any other text that contains sensitive, proprietary, export-controlled, or classified information. All requirements and context text are transmitted to a third-party AI provider (Anthropic or OpenAI) for analysis and are subject to their respective data handling policies.

---

## What You Need

- An API key from Anthropic or OpenAI (instructions below)
- Python and Node.js installed on your computer (instructions below)
- Visual Studio Code

---

## Step 1 — Install Python and Node.js (One Time Only)

### Python

1. Go to **https://www.python.org/downloads/**
2. Click the large **"Download Python 3.x.x"** button
3. Run the installer
4. **Critical — on the very first screen:** check the box **"Add Python to PATH"** before clicking anything else

   > If you miss this step the app will not work. Uninstall Python and reinstall if needed.

5. Click **Install Now**

### Node.js

1. Go to **https://nodejs.org/en**
2. Click the **"Get Node.js®"** button
3. Select the **LTS** version and download the installer for your operating system
4. Run the installer with all default options

---

## Step 2 — Get an API Key

You need one key — pick either Anthropic or OpenAI.

### Anthropic (Claude) — Recommended
1. Go to **https://console.anthropic.com/** and create an account
2. Click **API Keys** in the sidebar → **Create Key**
3. Copy the key — it starts with `sk-ant-`
4. Add at least $5 in credits at **https://console.anthropic.com/settings/billing**

### OpenAI (GPT-4o)
1. Go to **https://platform.openai.com/** and create an account
2. Go to **https://platform.openai.com/api-keys** → **Create new secret key**
3. Copy the key — it starts with `sk-`
4. Add at least $5 in credits at **https://platform.openai.com/account/billing**

> Keep your key private. Do not share it or paste it into any document.

---

## Step 3 — Download the Project

Go to the GitHub page for this project. Click the green **Code** button, then **Download ZIP**.

Unzip the downloaded file anywhere on your computer (Desktop is fine).

---

## Step 4 — Open in Visual Studio Code

If you don't have Visual Studio Code:
1. Go to **https://code.visualstudio.com/**
2. Click **Download for Windows** and install it

Open Visual Studio Code. Go to **File → Open Folder** and select the unzipped project folder.

---

## Step 5 — Start the App

In VSCode, open a terminal: **Terminal → New Terminal**

> **Windows only — run this once before anything else:**
> If you see an error saying "running scripts is disabled on this system", paste this into the terminal and press Enter:
> ```
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then continue below.

First, navigate into the project folder:

```
cd .\Requirements-Assistant-main\
```

Then run:

```
python3 run.py
```

**The first time you run this it will:**
1. Install all required packages automatically (takes 2–5 minutes)
2. Create a config file called `backend/.env`
3. Stop and ask you to add your API key to that file

**Add your API key:**

The file `backend/.env` will appear in the left file panel in VSCode under the `backend` folder. Click it to open it. It looks like this:

```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE
OPENAI_API_KEY=sk-YOUR-KEY-HERE
```

Replace the placeholder with your real key and set `AI_PROVIDER` to match:

```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-abc123...
```

Press **Ctrl+S** to save. Then run the command again:

```
python3 run.py
```

Your browser will open automatically at **http://localhost:3001**.

> To stop the app, press **Ctrl+C** in the terminal.

---

## How to Use the App

**1. Choose your AI provider**
Click Anthropic (Claude) or OpenAI (GPT-4o). If your key is already in `backend/.env` you will see a green confirmation and do not need to enter it again.

**2. Upload your requirements**
Click **Choose File** and select a `.txt` file with one requirement per line. Supported formats:

```
REQ-001: The system shall display GPS coordinates within 1 second.
REQ-002: The system shall alert the operator within 500 ms of a sensor failure.
```
```
1. The system shall display GPS coordinates within 1 second.
2. The system shall alert the operator within 500 ms of a sensor failure.
```
```
MR-C1.1: The system shall identify and tag potential targets using EO/IR sensor data.
MR-C1.2: The system shall transmit target coordinates within 500 ms.
```

**3. Upload context (optional but recommended)**
A `.txt` file describing the system. Significantly improves analysis quality. Example:

```
This system is an autonomous UAS designed for surveillance and reconnaissance
operating at altitudes up to 40,000 feet.
```

**4. Click Upload & Analyze**
Takes 15–60 seconds depending on how many requirements you have.

**5. Review results**
Each requirement shows which A2–A10 criteria it violates. For each violation choose:
- **Accept** — apply the suggested fix
- **Reject** — keep the original
- **Modify** — write your own correction

**6. Export**
Click **Submit** to download a corrected Word document (`.docx`).


---

## Troubleshooting

**"python is not recognized"**
Python was not added to PATH during install. Uninstall Python from Control Panel, re-download from python.org, and check "Add Python to PATH" on the first installer screen.

**"npm is not recognized"**
Node.js did not install correctly. Re-download from nodejs.org and run the installer again.

**Browser opens but "Request failed" appears**
The backend server did not start. Look at the VSCode terminal for error messages. Most common cause: `backend/.env` is missing or has the wrong key.

**"No API key provided" error**
Open `backend/.env` in VSCode and confirm your key is filled in and `AI_PROVIDER` matches the key you added (`anthropic` or `openai`).

**"Analysis failed" for all requirements**
Your API key account is out of credits. Log in to console.anthropic.com or platform.openai.com and add billing credits.

**App is slow**
Normal — each requirement makes one AI API call. A 10-requirement file takes 15–30 seconds. A 50-requirement file may take 2–3 minutes.
