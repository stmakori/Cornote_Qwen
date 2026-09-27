"""Views for the agent workflow: the Coach panel, exam date and manual re-plan."""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .agents import hooks
from .models import AgentRun, Notebook, StudyPlan


def _panel(request, notebook, error=None):
    plan = StudyPlan.objects.filter(notebook=notebook).first()
    runs = list(AgentRun.objects.filter(notebook=notebook, user=request.user)
                .exclude(agent=AgentRun.AGENT_COACH)[:6])
    today = timezone.localdate()
    return render(request, 'notebooks/partials/coach_panel.html', {
        'notebook': notebook,
        'plan': plan,
        'runs': runs,
        'running': any(r.status == AgentRun.STATUS_RUNNING for r in runs),
        'today': today,
        'days_left': (plan.exam_date - today).days if plan and plan.exam_date else None,
        'agents_enabled': hooks.enabled(),
        'error': error,
    })


@login_required
@require_GET
def coach_panel(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    return _panel(request, notebook)


@login_required
@require_POST
def set_exam_date(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    raw = (request.POST.get('exam_date') or '').strip()
    try:
        exam_date = date.fromisoformat(raw)
    except ValueError:
        return _panel(request, notebook, error='Pick a valid exam date.')
    if exam_date < timezone.localdate():
        return _panel(request, notebook, error='The exam date must be today or later.')
    plan, _ = StudyPlan.objects.get_or_create(notebook=notebook)
    plan.exam_date = exam_date
    plan.save(update_fields=['exam_date', 'updated_at'])
    hooks.exam_date_set(request.user, notebook)
    return _panel(request, notebook)


@login_required
@require_POST
def replan(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    StudyPlan.objects.get_or_create(notebook=notebook)
    hooks.replan(request.user, notebook)
    return _panel(request, notebook)
