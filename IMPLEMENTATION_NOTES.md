# Implementation Notes — OML input and locally hosted LLM

**Branch:** `feature/oml-input-and-local-llm`
**Base:** `main` (unchanged — nothing here was merged into it)

This note covers the two extensions asked for in the technical assessment:

1. The app can now accept a **`.oml` file** of requirements, in addition to `.txt`.
2. The app can now run its analysis on a **locally hosted LLM**, in addition to OpenAI and Anthropic.

Everything that worked before still works the same way. The existing analysis
pipeline, the prompts, and the INCOSE scoring logic were not touched.

---

## The short version

A requirements file arrives at one endpoint, `POST /api/upload`. Before this
change it was always handed to the line-based text parser. Now it is routed by
file extension: `.oml` goes to a new OML parser, everything else takes exactly
the path it always did.

The new parser returns requirements in the **same shape** the old one does —
`{'id', 'text', 'category'}`. That is the whole trick. Because the shape is
identical, nothing downstream of the upload endpoint has any idea which file
format the requirements came from. Analysis, review, feedback, and the Word
report all work on OML input without a single change.

The local LLM was added the same way: as one more branch in the function that
already chooses between Anthropic and OpenAI. It speaks the OpenAI protocol, so
it reuses the OpenAI client with a different `base_url` rather than introducing
a third kind of HTTP call to keep working.

```
                                    ┌─ .txt ──> requirements_parser ─┐
  upload ──> _parse_by_extension ───┤                                ├──> [ {id, text} ]
                                    └─ .oml ──> oml_parser ──────────┘          │
                                                                                v
                                                          analyse_all_requirements
                                                                                │
                                          ┌─────────────────┬───────────────────┤
                                          v                 v                   v
                                     anthropic           openai              local
                                                                        (OpenAI-compatible
                                                                          base_url swap)
```

---

## Where the changes are

| File | What changed | Why |
|---|---|---|
| `backend/oml_parser.py` | **New.** 259 lines. Extracts requirements from OML text. | The actual OML work. |
| `backend/main.py` | `_parse_by_extension()` at line 299; called from the upload endpoint at line 375. Provider config at lines 88–134. | Routes by extension; teaches the app that `local` is a valid provider. |
| `backend/ai_analyzer.py` | `local` provider branch at line 140; `_max_workers()` at line 306. | The local LLM call, and a lower concurrency cap for it. |
| `frontend/src/pages/UploadPage.jsx` | File picker accepts `.oml`; label and hint text updated; reports failed analyses. | So a user can actually select the file. |
| `backend/.env.example` | Documents the `LOCAL_LLM_*` settings. | Configuration reference. |
| `run.py` | Recognises `AI_PROVIDER=local`; prints local-model setup help. | The local-dev launcher would otherwise refuse to start without an API key. |
| `backend/tests/test_oml_parser.py` | **New.** 16 tests. | Covers the parser, including the malformed-input cases. |
| `backend/requirements-dev.txt` | **New.** `pytest` only. | Keeps the test dependency out of the deploy build. |
| `samples/PointMassRequirements.oml` | **New.** 13 real requirements. | Something to demo and test against. |

**Deliberately not changed:** `backend/requirements.txt`, `render.yaml`,
`Procfile`. The Render deployment builds and runs exactly as it did before.

---

## How the OML integration works

### What the parser reads

OML files come in two flavours. A **vocabulary** declares types — it says what a
`Requirement` *is*. A **description** declares instances — the actual
requirements of an actual system. Only descriptions contain requirements, so
that is the subset the parser handles.

A requirement in a description looks like this:

```
instance item-33334 : req:Requirement [
    tlo:hasName "Displace"
    tlo:hasID "33334"
    tlo:hasNaturalLanguageDescription "The System shall be able to move a point mass ..."
]
```

The parser walks the file and, for each named instance, asks three questions:

**1. Is this a requirement?**
It compares the *local name* of each of the instance's types against
`REQUIREMENT_TYPES`. Local name means the part after the last `:`, `#`, or `/`.
So `req:Requirement`, `mission:Requirement`, and
`<http://example.com/x#Requirement>` all reduce to `Requirement` and all match.

This matters because different projects import different vocabularies. Matching
the full IRI would mean the parser only ever worked with one lab's ontology.

**2. What is the requirement's text?**
It looks for a description property, checking these in order and taking the
first one that is present and non-empty:

```
hasNaturalLanguageDescription  →  hasDescription  →  hasStatement
                               →  hasText         →  hasCanonicalName
```

`hasCanonicalName` is last because it is usually a short label ("Displace")
rather than a full requirement statement. It is a fallback, not a preference.

If an instance has **no** description property at all, it is skipped rather than
passed on as an empty string. An empty string would come back from the analyser
with seven meaningless verdicts attached to it.

**3. What is its ID?**
`hasID`, `hasId`, or `hasIdentifier`. If the vocabulary asserts none of them,
the instance name (`item-33334`) is used instead, so the requirement can still
be traced back to its line in the model. `hasName` is carried through as the
optional `category` field — the same metadata slot the text parser fills from a
parenthesised label like `(Hardened)`.

### Why it is hand-written rather than a library

OML's canonical tooling is `openCAESAR`, which is Java and Gradle based. Pulling
that into a Python web app — or standing up a Gradle build step on Render —
would be a large dependency for a small job. The Python `rdflib` route does not
help either: it parses OML's *RDF projection*, not the `.oml` textual syntax
that a user actually has on disk and would upload.

Since the app needs one specific thing from the file — instances of a
requirement type and the prose asserted on them — a focused reader is the
smaller and more honest option. It adds no dependency and nothing new to the
deploy.

### The fiddly parts

A naive regex over the file breaks on real inputs. Three cases are handled
explicitly, and each has a test:

- **Brackets inside a requirement statement.** One of the sample requirements
  contains `[0.1"]` as an imperial-unit note. A bracket-counter that does not
  understand string literals would treat that as the end of the instance and
  truncate the requirement. `_bracketed_body` skips over string literals while
  tracking nesting depth.

- **Comments vs. IRIs.** Every OML file opens with something like
  `description <http://example.com/x#> as x`. Stripping `//` comments without
  care deletes the rest of that line and the file stops parsing.
  `_strip_comments` protects both string literals and IRIs.

- **Nested anonymous instances.** A value like `pizza:hasBase : pizza:DeepPanBase []`
  describes a *related* thing. Its properties are stepped over, not folded into
  the parent, so a nested object's `hasID` cannot silently become the
  requirement's ID.

Malformed input — an unclosed bracket or an unterminated string — raises
`ValueError`, which the upload endpoint turns into a **400** with the reason in
the message. A file with valid syntax but no requirements in it also returns a
400 explaining what was expected, rather than an empty and confusing analysis.

---

## How the local LLM was integrated

### The approach

The assessment left the integration approach open. I used **the OpenAI
chat-completions protocol as the interface**, rather than targeting one specific
runtime.

That protocol has become the de-facto standard that self-hosted servers
implement. Ollama exposes it at `/v1`, and so do vLLM, llama.cpp's server,
LM Studio, text-generation-webui, and hosted on-prem gateways such as Virginia
Tech ARC's `llm-api.arc.vt.edu`. Because the `openai` package is *already* a
dependency of this project, supporting all of them is a `base_url` swap:

```python
client = openai_lib.OpenAI(
    api_key=api_key or os.getenv("LOCAL_LLM_API_KEY", "") or "not-required",
    base_url=os.getenv("LOCAL_LLM_URL"),
)
```

The alternative — writing a bespoke HTTP client per runtime, the way the legacy
`ollama` branch does — means a new code path to maintain for every server
someone wants to use. This way, switching from a laptop running Ollama to a
cluster running vLLM is a change to `.env`, not a change to the code.

### Configuration

All of it lives in `backend/.env`:

| Setting | What it does |
|---|---|
| `AI_PROVIDER=local` | Selects the local model. |
| `LOCAL_LLM_URL` | The endpoint, including `/v1`. **This is what switches the provider on.** |
| `LOCAL_LLM_API_KEY` | Only needed by servers that check one. Leave empty otherwise. |
| `LOCAL_LLM_MODEL` | Model name the server expects, e.g. `gpt-oss-120b`, `llama3`. |
| `LOCAL_LLM_MAX_TOKENS` | Default `4000`. See below. |
| `LOCAL_LLM_JSON_MODE` | Default on. Set to `0` for servers that reject `response_format`. |

Examples:

```bash
# Ollama on the same machine — no key needed
LOCAL_LLM_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=llama3

# VT ARC hosted endpoint — key from llm.arc.vt.edu
LOCAL_LLM_URL=https://llm-api.arc.vt.edu/api/v1
LOCAL_LLM_API_KEY=sk-...
LOCAL_LLM_MODEL=gpt-oss-120b
```

### Three things a local model needed that a hosted API did not

**1. It is configured by URL, not by key.**
The app decides which providers to offer by checking whether a key is set. A
self-hosted server frequently authenticates nothing at all, so that check would
hide a perfectly working model. `_provider_configured()` in `backend/main.py`
treats `local` as ready when `LOCAL_LLM_URL` is set, and the other providers as
ready when their key is set.

**2. Reasoning models need a much larger token budget.**
The hosted providers are called with `max_tokens=1200`. A reasoning model spends
that budget *thinking* before it emits the first character of its answer, and
vLLM charges those thinking tokens against `max_tokens`. At 1200, `gpt-oss-120b`
was cut off mid-thought and returned **no content at all** — roughly 1900 was
needed for a single requirement. The default here is 4000.

That failure is also now reported instead of being swallowed. Previously a
`None` message content raised an `AttributeError`, which was caught per
requirement and recorded as "could not evaluate" against all seven criteria —
and the violation counter reads seven unevaluated criteria as **zero
violations**, i.e. a clean pass. The local branch raises a named error that says
to raise `LOCAL_LLM_MAX_TOKENS`, and `/api/upload` now returns an
`errors_count` so a broken run is visibly different from a clean one.

**3. Fewer concurrent requests, not more.**
Hosted APIs are fanned out to 10 workers. One GPU serves requests from a single
queue, so fanning out 10 does not make them finish sooner — it just multiplies
each one's latency. VT ARC's endpoint also caps a user at 10 concurrent
requests, which the old default sat exactly on. `_max_workers()` uses 4 for the
local provider and leaves the hosted providers at 10.

### The legacy `ollama` provider

It still exists and still works, untouched. `AI_PROVIDER=local` with
`LOCAL_LLM_URL=http://localhost:11434/v1` is the better route — it uses Ollama's
OpenAI-compatible endpoint and gets JSON mode — but nothing that worked before
was removed.

---

## Dependencies introduced

**Runtime: none.** `backend/requirements.txt` is unchanged. The OML parser uses
only the standard library (`re`, `typing`), and the local LLM reuses the
`openai` package that was already there.

**Development: one.** `pytest==8.3.3`, in a new `backend/requirements-dev.txt`.
It is kept separate from `requirements.txt` on purpose, so the Render build
installs exactly what it installed before.

---

## How to test it

### Setup

```bash
git checkout feature/oml-input-and-local-llm
python -m venv venv
venv/Scripts/activate            # macOS/Linux: source venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

### 1. Unit tests — the OML parser

```bash
python -m pytest backend/tests -q
```

Expect **16 passed**. They cover extraction from the real sample file, the
pipeline-shape contract, type matching on local names, text-property precedence,
ID fallback, skipping instances with no prose, ignoring non-requirement
instances, brackets and escaped quotes inside literals, nested instances, comment
stripping with IRIs intact, and both malformed-input rejections.

### 2. Run the app against a local model

Install [Ollama](https://ollama.com), then:

```bash
ollama pull llama3
```

Put this in `backend/.env`:

```
AI_PROVIDER=local
LOCAL_LLM_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=llama3
```

Then:

```bash
python run.py
```

The app opens at http://localhost:3001. Upload `samples/PointMassRequirements.oml`,
leave the context file empty, and click analyse. You should get **13
requirements**, each scored against all seven criteria.

To confirm the provider is really the local one, check `/api/config` — it should
list "Local / self-hosted" and report `ready: true`.

### 3. Confirm nothing regressed

Upload `samples/sample_requirements.txt` the same way. It should behave exactly
as it always has — 5 requirements, same output format, same Word document.

### What has actually been verified

Both features were driven end to end through the real `/api/upload` endpoint,
with a stub OpenAI-compatible server standing in for the model:

| Check | Result |
|---|---|
| `.oml` upload → analysis | 13/13 requirements, `errors_count: 0` |
| IDs and text survive the handoff | `33334` → "The System shall be able to move a point mass…" |
| Criteria per requirement | 7 |
| Local provider actually called | 13 calls, correct model name, JSON mode on |
| Report generation | feedback → `/api/download/docx` → valid 38 KB `.docx` |
| `.txt` regression | 5 requirements, unchanged |
| Local provider misconfigured | 503 naming `LOCAL_LLM_URL`, not a silent failure |

The stub returns canned verdicts, so this verifies the plumbing — request shape,
response parsing, threading, error handling — not the judgement quality of any
particular model.

---

## Assumptions

1. **Requirements live in OML descriptions, not vocabularies.** A vocabulary
   declares what a requirement *is*; only a description contains actual
   requirements. Uploading a vocabulary returns a 400 saying no requirements
   were found.

2. **A requirement is an instance whose type's local name is `Requirement`.**
   Namespace prefix is ignored so the parser is not tied to one project's
   ontology. If a project uses a different word entirely — `Constraint`,
   `Shall` — that word needs adding to `REQUIREMENT_TYPES` in
   `backend/oml_parser.py`. It is a one-line change and the list is at the top
   of the file for that reason.

3. **The requirement's prose is what gets analysed.** Every INCOSE A-criterion
   in this tool is a judgement about English wording, so the natural-language
   description is the property the pipeline needs. Relations between
   requirements (`refines`, `derivedFrom`) are read past, not used. They would
   matter for *set*-level analysis, which is out of scope here.

4. **First assertion wins** when a property is asserted more than once on the
   same instance. This matches how the rest of the pipeline treats a repeated
   field.

5. **Any OpenAI-compatible server is an acceptable "locally hosted LLM."** This
   covers a model on the user's own machine and one on institutional hardware
   they control. Both keep requirement text off commercial APIs, which is the
   point of the requirement for a DOE project.

6. **The operator configures the model, not the end user.** This follows the
   existing security design: users never see or enter a key or an endpoint.
   Local settings are read from server environment only.

7. **Files are UTF-8.** Decoded with `errors='replace'`, matching how `.txt`
   uploads were already handled.

---

## Possible next steps

Not implemented, and not in scope, but worth noting:

- **Round-trip the results back into OML.** Right now OML is an input format
  only. Writing the accepted rewrites back as an OML description would close the
  loop with the modelling tools the requirements came from.

- **Use the relations the parser currently reads past.** `refines` and
  `derivedFrom` describe the structure of the requirement set. The set-level
  analysis already in the codebase could use that structure directly instead of
  inferring it.

- **Extend to OML vocabularies and the RDF projection**, so a project that keeps
  requirements in `.ttl` alongside `.oml` can upload either.

- **Streaming progress for local models.** A local model is slower than a hosted
  API, and with 4 workers a large set takes noticeably longer. The UI currently
  shows a progress bar driven by request count; per-requirement streaming would
  make the wait legible.

- **Pin the local model's identity in the report.** The Word report records the
  analysis but not which model produced it. With a swappable local endpoint that
  provenance matters more than it did with a single fixed provider.
