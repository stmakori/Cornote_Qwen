# Cornote

### 🔴 Live demo: [https://bit.ly/4AF7FcM](https://bit.ly/4AF7FcM)

**Your PDF. Your Questions. Your Cornell Notes. Instantly.**

Cornote turns any PDF into a complete, interactive Cornell study session. Upload a
lecture or textbook PDF and Cornote extracts structured Cornell style notes,
generates practice questions, grades your answers with real AI feedback, and keeps
adjusting your study plan every time you use it, all in one distraction free page
with a built in Pomodoro timer.

Built for university students studying from PDFs, starting with Kenya and
Sub Saharan Africa, where over 80% of students study primarily from PDFs and the
Cornell method is virtually unknown in most classrooms.

See [PROBLEM.md](PROBLEM.md) for the full problem statement.

## The underlying magic: four autonomous Claude agents

This is the part we are most proud of. Cornote does not call an AI model once and
show you the answer. It runs **four autonomous Claude agents in production**,
each with a goal and a set of tools, deciding for themselves what to do next:

| Agent | What it does |
| --- | --- |
| **Feedback agent** | Diagnoses a wrong answer, cites the exact passage from the student's own notes, and schedules a targeted follow up question for the next session. |
| **Study plan agent** | Builds a day by day schedule to the exam date from real performance data, and re plans automatically every time the student grades new answers. |
| **Verifier agent** | Checks every AI generated question against the source notes before a student ever sees it, catching unsupported or misleading questions. |
| **Coach agent** | Powers the tutor chat. Searches the student's own notes, checks their performance history, and assigns practice on its own, with no fixed script. |

The loop is simple and built entirely in house: **Claude reasons, calls a tool,
our own Python code runs it, the result feeds back, and Claude continues, until it
gives a final answer.** No Strands, no LangChain, no third party agent framework,
just the official `anthropic` SDK and 8 tools we wrote ourselves, each one scoped so
an agent can only ever touch the current student's own notebook.

**Live today: 4 agents shipped, 237/237 tests passing, zero external
agent-framework dependencies.**

See [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) for how each agent is triggered, what
tools it can call, and the safety limits (tool call budgets, prompt injection
guards, automatic fallback to plain grading and chat if an agent fails).

## Key features

- **Instant Cornell notes.** Upload a PDF (or Markdown/text) up to 50MB and get
  structured Cornell style notes with an AI summary, in text and audio, in
  under a minute.
- **AI generated practice questions** across 7 types: short answer, multiple
  choice, true/false, fill in the blank, multiple select, matching, and
  ordering.
- **Real grading, not keyword matching.** Structured questions are graded
  instantly; free text answers get AI feedback plus progressive hints.
- **Spaced repetition and exam mode.** A review queue (SM-2) built from
  questions you missed, plus a full timed exam simulation.
- **A tutor chat grounded in your own notes**, now agentic: it can look things
  up, check your performance, and assign you practice on its own.
- **Math support**: LaTeX rendering and symbolic grading, with Claude vision
  transcribing scanned handwritten or printed math that OCR alone mangles.
- **Teacher and classroom tools**: assign question sets with due dates, track
  per class accuracy, and grade submissions automatically.
- **Gamification and study groups**: badges, streaks, leaderboards, and
  shared study groups to keep students engaged.
- **Built in Pomodoro timer** and a distraction free, single page workspace.

## Current progress

Cornote is a working, deployed Django application with the full study loop
implemented end to end:

- **Done:** PDF/text/Markdown ingestion, note generation, all 7 question
  types with instant and AI grading, progressive hints, spaced repetition,
  exam mode, learning paths, the 4 agent workflow above, math support (LaTeX
  and symbolic grading), teacher and class assignments with statistics, study
  groups, gamification, notebook sharing, notifications, PDF and Anki export,
  and a demo data seeding command so anyone can try the app without uploading
  their own PDF.
- **Next:** expanding automated test coverage further, polishing the
  teacher facing analytics views, and the go to market plan in the pitch deck
  (campus rollout, then institutional partnerships, then regional expansion
  beyond Kenya).

## Tech stack

- **Backend:** Django 5.1, SQLite (or any `DATABASE_URL` via `dj-database-url`)
- **Frontend:** Django templates, HTMX, Bootstrap 5, and vanilla JS. No SPA
  framework.
- **AI:** Anthropic Claude (`claude-sonnet-5`), the single AI provider for
  notes, questions, grading, hints, tutor chat, scanned math OCR, and all four
  agents.
- **Agents:** a native Claude tool calling loop built directly on the
  `anthropic` SDK, no external agent framework.
- **Audio:** gTTS for generated audio summaries.
- **Static files:** WhiteNoise.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

cp .env.example .env          # fill in SECRET_KEY, ANTHROPIC_API_KEY, etc.

python manage.py migrate
python manage.py runserver
```

Then visit `http://127.0.0.1:8000/`.

### Try it without your own PDF

```bash
python manage.py seed_demo_data
```

This creates (or resets) a demo account pre-loaded with a notebook, questions of
every type in various grading states, a learning path, badges, and a study group,
so you can explore the whole app immediately. The landing and login pages have a
"Try Demo" button that logs straight into this account, re-seeding it fresh each
time so one visitor poking around does not spoil it for the next.

## Environment variables

See `.env.example` for the full list. At minimum you need `SECRET_KEY` and
`ANTHROPIC_API_KEY` to use the AI features and the agent workflow.
`AGENTS_ENABLED` turns the four agents off entirely if set to `False`, and
Cornote falls back to plain single call grading and chat. `EMAIL_BACKEND`
defaults to Django's console backend, so password reset emails print to the
`runserver` log instead of sending real mail. That is fine for local dev; swap
in a real backend for production.

## Running tests

```bash
python manage.py test apps.notebooks apps.users
```

237 tests, all passing, including the agent workflow tests. The test suite never
calls a real AI provider; `AGENTS_ENABLED` is forced off under `manage.py test`
and the Claude client is mocked.

## AI and tool disclosure

- **Model:** Anthropic Claude (`claude-sonnet-5`), the sole AI provider for the
  entire app. No other model provider is used.
- **Agents:** four autonomous agents (feedback, study plan, verifier, coach)
  built on a native tool calling loop on top of the official `anthropic` Python
  SDK. No external agent framework (no Strands, no LangChain). 8 tools, each
  scoped to one student's own notebook. Every agent run and tool call is
  logged and shown to the student in the Cornote Coach panel.
- **NVIDIA Brev / NVIDIA Build:** not used in the current build.
- **Fallback:** if an agent run fails or Claude is not configured, Cornote
  falls back to the original single call grading and tutor chat. Nothing is
  ever left broken for the student.
- **Vision:** Claude also transcribes scanned math pages into LaTeX when
  Tesseract OCR alone cannot handle handwritten or complex notation.

## Team

- **Stephanie Makori**, Co-Founder and Developer, AI and Engineering.
- **Sally Munga**, Co-Founder and Developer, AI and Engineering.

## Security notes

- `.env.example` is the template committed for anyone cloning the repo. Real
  `.env` files are gitignored by default (`.env`, `.env.*`) so a fresh clone
  never accidentally commits credentials.
- Media files (`media/`) and the SQLite database (`db.sqlite3`) stay
  gitignored; they contain user uploaded documents and should not be pushed
  to a shared repo.
- Never put real API keys, passwords, or voucher codes in this repository, a
  demo video, or anywhere public.
