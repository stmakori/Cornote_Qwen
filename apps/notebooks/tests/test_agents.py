"""Tests for the agent workflow: tools, the Claude tool-use loop, workflows and triggers.

No real AI calls: the model loop is mocked, tools run against the test database.
"""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.notebooks.agents import llm, workflows
from apps.notebooks.agents.tools import AgentContext, build_tools, search_passages
from apps.notebooks.models import AgentRun, Answer, Notebook, Question, QuestionReview, StudyPlan

NOTES = (
    'Photosynthesis happens in the chloroplast. Light energy is converted into chemical energy.\n\n'
    'Cellular respiration happens in the mitochondria and releases ATP from glucose.\n\n'
    'Osmosis is the movement of water across a semi-permeable membrane.'
)


def tools_by_name(ctx, names):
    return dict(zip(names, build_tools(ctx, names)))


class AgentTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='student', password='pw')
        self.other = User.objects.create_user(username='other', password='pw')
        self.notebook = Notebook.objects.create(
            user=self.user, title='Biology', pdf_file='fake.txt', pdf_text=NOTES, notes_content=NOTES,
            status=Notebook.STATUS_READY, processing_stage=Notebook.STAGE_READY,
        )
        self.q1 = Question.objects.create(
            notebook=self.notebook, question_text='Where does respiration happen?',
            expected_answer='In the mitochondria', expected_keywords=['mitochondria'], order_index=1,
        )
        Answer.objects.create(question=self.q1, user=self.user, user_answer='chloroplast',
                              grade=Answer.GRADE_INCORRECT, feedback='Not quite.')
        self.ctx = AgentContext(user=self.user, notebook=self.notebook)


class SearchTests(AgentTestBase):
    def test_finds_the_right_passage(self):
        hits = search_passages(NOTES, 'mitochondria respiration ATP')
        self.assertEqual(hits[0][0], 2)
        self.assertIn('mitochondria', hits[0][2])

    def test_search_notes_tool_returns_citable_passage_and_logs_step(self):
        t = tools_by_name(self.ctx, ['search_notes'])
        result = t['search_notes'](query='osmosis water membrane')
        self.assertIn('[P3]', result)
        self.assertEqual(self.ctx.steps[0]['tool'], 'search_notes')


class ToolTests(AgentTestBase):
    def test_get_question_is_scoped_to_notebook(self):
        foreign = Notebook.objects.create(user=self.other, title='Other', pdf_file='x.txt')
        foreign_q = Question.objects.create(notebook=foreign, question_text='Secret?')
        t = tools_by_name(self.ctx, ['get_question'])
        self.assertIn('not found', t['get_question'](question_id=foreign_q.pk))
        data = json.loads(t['get_question'](question_id=self.q1.pk))
        self.assertEqual(data['student_answer'], 'chloroplast')

    def test_followup_is_created_scheduled_tomorrow_and_deduplicated(self):
        t = tools_by_name(self.ctx, ['create_followup_question'])
        args = dict(source_question_id=self.q1.pk, question_text='What organelle releases ATP?',
                    expected_answer='Mitochondria', expected_keywords=['mitochondria'], mistake_type='missed_concept')
        t['create_followup_question'](**args)
        t['create_followup_question'](**{**args, 'question_text': 'Name the organelle for respiration.'})
        followups = Question.objects.filter(source_question=self.q1, created_by_agent=True)
        self.assertEqual(followups.count(), 1)  # second call updated, didn't duplicate
        followup = followups.get()
        self.assertEqual(followup.question_text, 'Name the organelle for respiration.')
        self.assertTrue(hasattr(followup, 'answer'))
        review = QuestionReview.objects.get(question=followup, user=self.user)
        self.assertGreater(review.next_review, timezone.now() + timedelta(hours=20))

    def test_followup_limit_per_run(self):
        t = tools_by_name(self.ctx, ['create_followup_question'])
        for i in range(3):
            q = Question.objects.create(notebook=self.notebook, question_text=f'Q{i}', order_index=10 + i)
            Answer.objects.create(question=q)
            result = t['create_followup_question'](
                source_question_id=q.pk, question_text=f'F{i}', expected_answer='a',
                expected_keywords=[], mistake_type='careless_slip')
        self.assertIn('limit', result)
        self.assertEqual(Question.objects.filter(created_by_agent=True).count(), 2)

    def test_save_study_plan_validates_and_versions(self):
        t = tools_by_name(self.ctx, ['save_study_plan'])
        today = timezone.localdate()
        days = [
            {'date': (today - timedelta(days=1)).isoformat(), 'focus': 'past', 'tasks': ['x'], 'minutes': 30},
            {'date': today.isoformat(), 'focus': 'Respiration', 'tasks': 'Re-read P2', 'minutes': 9999},
            {'date': 'not-a-date', 'focus': 'bad'},
        ]
        result = t['save_study_plan'](days=days, rationale='Weakest topic first.')
        self.assertIn('v1', result)
        plan = StudyPlan.objects.get(notebook=self.notebook)
        self.assertEqual(len(plan.days), 1)
        self.assertEqual(plan.days[0]['tasks'], ['Re-read P2'])
        self.assertEqual(plan.days[0]['minutes'], 240)

    def test_tool_budget_stops_runaway_agents(self):
        t = tools_by_name(self.ctx, ['search_notes'])
        with override_settings(AGENT_MAX_TOOL_CALLS=2):
            t['search_notes'](query='osmosis')
            t['search_notes'](query='osmosis')
            self.assertIn('budget', t['search_notes'](query='osmosis'))


class LlmLoopTests(AgentTestBase):
    """The native Claude tool-use loop in llm.py, with the Anthropic client mocked."""

    @override_settings(ANTHROPIC_API_KEY='')
    def test_no_api_key_raises_agent_unavailable(self):
        with self.assertRaises(llm.AgentUnavailable):
            llm.run_agent(self.ctx, 'sys', 'hi', [])

    @override_settings(ANTHROPIC_API_KEY='test-key', AGENT_MODEL_ID='claude-test')
    def test_calls_a_tool_then_returns_the_final_answer(self):
        tool_use = SimpleNamespace(
            type='tool_use', name='search_notes', input={'query': 'mitochondria'}, id='toolu_1',
        )
        final_text = SimpleNamespace(type='text', text='Mitochondria release ATP [P2].')
        fake_client = Mock()
        fake_client.messages.create.side_effect = [
            SimpleNamespace(content=[tool_use]),
            SimpleNamespace(content=[final_text]),
        ]

        with patch.object(llm, '_get_client', return_value=fake_client):
            text, provider = llm.run_agent(self.ctx, 'sys', 'What organelle handles respiration?', ['search_notes'])

        self.assertEqual(text, 'Mitochondria release ATP [P2].')
        self.assertEqual(provider, 'Claude (claude-test)')
        self.assertEqual(fake_client.messages.create.call_count, 2)
        self.assertEqual(self.ctx.steps[0]['tool'], 'search_notes')  # the real tool ran, not a stub

    @override_settings(ANTHROPIC_API_KEY='test-key')
    def test_client_error_raises_agent_unavailable_and_logs_a_step(self):
        fake_client = Mock()
        fake_client.messages.create.side_effect = RuntimeError('rate limited')

        with patch.object(llm, '_get_client', return_value=fake_client):
            with self.assertRaises(llm.AgentUnavailable):
                llm.run_agent(self.ctx, 'sys', 'hi', [])

        self.assertEqual(self.ctx.steps[-1]['tool'], 'provider_error')


class WorkflowTests(AgentTestBase):
    def test_run_records_output_steps_and_provider(self):
        def fake_run(ctx, system_prompt, prompt, tool_names):
            build_tools(ctx, ['search_notes'])[0](query='mitochondria')
            return 'Why it was marked wrong...', 'Claude (test)'
        with patch.object(workflows, 'run_agent', side_effect=fake_run):
            run = workflows.run_feedback(self.user, self.notebook, self.q1)
        self.assertEqual(run.status, AgentRun.STATUS_OK)
        self.assertEqual(run.provider, 'Claude (test)')
        self.assertEqual(run.steps[0]['tool'], 'search_notes')

    def test_failure_is_recorded_not_raised(self):
        with patch.object(workflows, 'run_agent', side_effect=llm.AgentUnavailable('down')):
            run = workflows.run_study_plan(self.user, self.notebook)
        self.assertEqual(run.status, AgentRun.STATUS_FAILED)
        self.assertIn('down', run.error)


@override_settings(AGENTS_ENABLED=True, AGENTS_RUN_INLINE=True)
class TriggerTests(AgentTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_grading_triggers_feedback_agent_and_replan(self):
        StudyPlan.objects.create(notebook=self.notebook)
        from apps.notebooks.services import ai_service
        graded = [{'ok': True, 'grade': 'incorrect', 'feedback': 'Wrong organelle.'}]
        with patch.object(workflows, 'run_agent', return_value=('ok', 'Claude')), \
             patch.object(ai_service, 'grade_answer_batch', return_value=graded):
            response = self.client.post(reverse('notebooks:grade_answers', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['HX-Trigger'], 'coachRefresh')
        agents = list(AgentRun.objects.order_by('created_at').values_list('agent', flat=True))
        self.assertEqual(agents, [AgentRun.AGENT_FEEDBACK, AgentRun.AGENT_STUDY_PLAN])

    def test_setting_exam_date_triggers_study_plan_agent(self):
        exam = (timezone.localdate() + timedelta(days=5)).isoformat()
        with patch.object(workflows, 'run_agent', return_value=('Plan created: ...', 'Claude')):
            response = self.client.post(reverse('notebooks:set_exam_date', args=[self.notebook.pk]), {'exam_date': exam})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudyPlan.objects.get(notebook=self.notebook).exam_date.isoformat(), exam)
        self.assertTrue(AgentRun.objects.filter(agent=AgentRun.AGENT_STUDY_PLAN).exists())
        self.assertContains(response, 'Plan created')

    def test_past_exam_date_rejected(self):
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.client.post(reverse('notebooks:set_exam_date', args=[self.notebook.pk]), {'exam_date': past})
        self.assertContains(response, 'today or later')

    def test_chat_uses_coach_agent(self):
        with patch.object(workflows, 'run_agent', return_value=('Mitochondria release ATP [P2].', 'Claude')):
            response = self.client.post(reverse('notebooks:notebook_chat', args=[self.notebook.pk]),
                                        {'message': 'What releases ATP?'})
        self.assertContains(response, '[P2]')

    def test_chat_falls_back_to_plain_tutor_when_agent_fails(self):
        from apps.notebooks.services import ai_service
        with patch.object(workflows, 'run_agent', side_effect=llm.AgentUnavailable('down')), \
             patch.object(ai_service, 'answer_notebook_question', return_value='Plain answer.'):
            response = self.client.post(reverse('notebooks:notebook_chat', args=[self.notebook.pk]),
                                        {'message': 'What releases ATP?'})
        self.assertContains(response, 'Plain answer.')

    def test_coach_panel_only_for_owner(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('notebooks:coach_panel', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)
