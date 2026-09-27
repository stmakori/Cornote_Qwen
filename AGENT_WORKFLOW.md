# Cornote agent workflow

Cornote's AI now works as a set of agents instead of one-shot calls. Each agent is given a goal
and a set of tools, and Claude decides the steps itself — which tool to call, in what order, how
many times — and loops until the goal is met or the tool-call budget runs out.

- **Brain:** Anthropic Claude, using the same credentials already configured for the rest of the app.
- **Loop:** a native tool-use loop on the `anthropic` SDK (`apps/notebooks/agents/llm.py`) — no
  separate agent framework.
- **Hands:** tools in `apps/notebooks/agents/tools.py`, each limited to one student's own notebook.

## Setup (about 2 minutes)

1. Migrate: `python manage.py migrate`
2. Test: `python manage.py test apps.notebooks apps.users`
3. Run: `python manage.py runserver`

No new secrets are required — `AGENT_MODEL_ID` defaults to the already-configured
`ANTHROPIC_MODEL_ID`. Turn every agent off at once with `AGENTS_ENABLED=False`; Cornote then
behaves exactly as before.

## The four agents

| Agent | Trigger | Tools |
| --- | --- | --- |
| Feedback | Wrong/partial answer after **Grade All** | `get_question` → `search_notes` → `create_followup_question` |
| Study plan | Exam date set in the Coach panel; **automatically after every grading** once a plan exists; manual re-plan button | `get_schedule_context` → `get_performance` → `save_study_plan` |
| Verifier | After a new PDF's questions are generated | `list_questions` → `search_notes` → `flag_question` |
| Coach | Tutor chat messages | `search_notes`, `get_performance`, `get_schedule_context`, `create_followup_question` |

Follow-up questions appear in the notebook with a robot note ("Follow-up to Q3 (missed concept)")
and are due in the spaced-repetition queue tomorrow. Flagged questions get a flag and the verifier's reason.

The **Cornote Coach** panel on the notebook page shows the exam date, the current plan and the
latest agent runs, including every tool step ("What the agent did").

## Safety and reliability

- Tools can only touch the current student's notebook (checked on every call).
- Max tool calls per run (`AGENT_MAX_TOOL_CALLS`), max 2 follow-ups per run, max 3 feedback runs per grading, plans capped at 14 days (`AGENT_MAX_PLAN_DAYS`).
- Notes and answers are treated as data, never as instructions (prompt-injection guard in every system prompt).
- If Claude fails or isn't configured, the run is logged as failed and Cornote falls back to the original behaviour (plain grading, plain tutor chat).
- Feedback and re-planning run in a background thread, so grading stays fast.
- The test suite never calls a real AI provider (`AGENTS_ENABLED` is forced off under `manage.py test`).

## Demo script

1. Upload a text PDF. Coach panel: **Question verifier: done** (open "What the agent did").
2. Set an exam date in 4 days → **Plan created** with a day-by-day table.
3. Answer a question wrong → **Grade All**.
4. Coach panel: **Feedback agent** explains why, cites `[P#]`, and a follow-up question appears.
5. **Plan updated** automatically, without asking, now prioritising that topic.
