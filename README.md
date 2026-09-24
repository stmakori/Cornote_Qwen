# Cornote

Cornote turns a PDF into a full study loop: Cornell-style notes, auto-graded
practice questions, spaced repetition, exam simulation, a tutor chat, learning
paths, gamification, and teacher/class tools — all built on Django.

## Problem

Turning reading material into effective, active-recall study practice is slow
and manual. Students either re-read passively (which doesn't build recall) or
spend hours by hand converting a textbook chapter or lecture PDF into
flashcards, quiz questions, and a review schedule. Teachers face the same
bottleneck when they want to check understanding: writing question sets by
hand for every reading, grading free-text answers one by one, and tracking
which students are behind. Most existing tools only solve one piece of this
(notes, or flashcards, or quizzes) rather than the whole loop from "here's a
PDF" to "here's a graded, spaced, trackable study plan."

See [PROBLEM.md](PROBLEM.md) for more on who this affects and why it matters.

## Proposed solution

Upload a PDF (or Markdown/text), and Cornote automatically:

- Extracts and reformats the content into structured Cornell-style notes with
  an AI summary (text + audio).
- Generates practice questions across 7 types (short answer, multiple choice,
  true/false, fill-in-the-blank, multiple select, matching, ordering).
- Grades answers instantly for structured question types, and grades
  free-text answers with AI feedback plus progressive hints.
- Builds a spaced-repetition review queue (SM-2) from questions missed, and
  offers a full exam-simulation mode.
- Breaks the material into an ordered learning path of topics.
- Adds a tutor chat grounded in the notebook's own content.
- Supports teacher/class workflows: assign question sets with due dates,
  track per-class accuracy, and grade submissions automatically.
- Layers in gamification (badges, streaks, leaderboards) and study groups to
  keep students engaged.

## Current progress

Cornote is a working Django application with the full study loop implemented
end to end:

- **Done:** PDF/text/Markdown ingestion, note generation, all 7 question
  types with instant + AI grading, progressive hints, spaced repetition,
  exam mode, learning paths, tutor chat, math support (LaTeX + symbolic
  grading), teacher/class assignments with statistics, study groups,
  gamification (badges/streaks/leaderboard), notebook sharing, notifications,
  PDF/Anki export, and a demo-data seeding command for trying the app without
  uploading your own PDF.
- **In progress / next:** hardening the AI grading and generation pipeline,
  expanding automated test coverage, and polishing the teacher-facing
  analytics views.

## Tech stack

- **Backend:** Django 5.1, SQLite (or any `DATABASE_URL` via `dj-database-url`)
- **Frontend:** Django templates + HTMX + Bootstrap 5 + vanilla JS (no SPA
  framework)
- **AI:** Qwen (via an OpenAI-compatible API) for notes, questions, grading,
  hints, and tutor chat; Anthropic Claude for scanned-page math OCR/vision
  transcription
- **Audio:** gTTS for generated audio summaries
- **Static files:** WhiteNoise

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

cp .env.example .env          # fill in SECRET_KEY, QWEN_API_KEY, etc.

python manage.py migrate
python manage.py runserver
```

Then visit `http://127.0.0.1:8000/`.

### Try it without your own PDF

```bash
python manage.py seed_demo_data
```

This creates (or resets) a `demo` account pre-loaded with a notebook, questions of
every type in various grading states, a learning path, badges, and a study group —
so you can explore the whole app immediately. The landing and login pages have a
"Try Demo" button that logs straight into this account (re-seeding it fresh each
time, so one visitor poking around doesn't spoil it for the next).

## Environment variables

See `.env.example` for the full list. At minimum you need `SECRET_KEY` and
`QWEN_API_KEY` to use the AI features; `ANTHROPIC_API_KEY` is optional and only
needed for scanned-page math OCR (falls back to Tesseract without it).
`EMAIL_BACKEND` defaults to Django's console backend, so password-reset emails
print to the `runserver` log instead of sending real mail — fine for local dev,
swap in a real backend for production.

## Running tests

```bash
python manage.py test apps.notebooks apps.users
```

## Security notes

- `.env` (and any `.env.*` file) is gitignored — never commit real credentials.
- Media files (`media/`) and the SQLite database (`db.sqlite3`) are also
  gitignored; they contain user-uploaded documents and should not be pushed to a
  shared repo.
