import threading
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django_htmx.http import HttpResponseClientRedirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.db.models import Q

from .models import Notebook, Question, Answer, Summary, StudySession
from .forms import PDFUploadForm, NotesEditForm, SummaryForm
from .services.pdf_processor import truncate_for_ai
from .services.document_processor import extract_document_text, tesseract_ocr_available
from .services import ai_service
from .services.features_service import (
    AnalyticsService, SpacedRepetitionService, AchievementService,
    NotificationService, ExamService, LearningPathService, PreferencesService
)

logger = logging.getLogger(__name__)


def _process_notebook(notebook_id: int):
    """Background thread: extract document text, AI key points & questions (resumable by processing_stage)."""
    from django.db import connection

    try:
        notebook = Notebook.objects.get(pk=notebook_id)
        notebook.status = Notebook.STATUS_PROCESSING
        notebook.save(update_fields=['status'])

        file_path = notebook.pdf_file.path
        original_name = notebook.pdf_file.name

        if notebook.processing_stage < Notebook.STAGE_TEXT:
            body = extract_document_text(file_path, original_name)
            notebook.pdf_text = body
            notebook.notes_content = body
            notebook.processing_stage = Notebook.STAGE_TEXT
            notebook.save(update_fields=['pdf_text', 'notes_content', 'processing_stage'])

        truncated = truncate_for_ai(notebook.pdf_text)

        if notebook.processing_stage < Notebook.STAGE_SUMMARY_KEYS:
            key_points = ai_service.extract_key_points(truncated)
            Summary.objects.update_or_create(
                notebook=notebook,
                defaults={'key_points': key_points},
            )
            notebook.processing_stage = Notebook.STAGE_SUMMARY_KEYS
            notebook.save(update_fields=['processing_stage'])

        if notebook.processing_stage < Notebook.STAGE_QUESTIONS:
            questions_data = ai_service.generate_questions(truncated)
            Question.objects.filter(notebook=notebook).delete()
            for idx, q_data in enumerate(questions_data):
                question = Question.objects.create(
                    notebook=notebook,
                    question_text=q_data.get('question_text', ''),
                    expected_answer=q_data.get('expected_answer', ''),
                    expected_keywords=q_data.get('expected_keywords', []),
                    order_index=idx + 1,
                )
                Answer.objects.create(question=question)
            notebook.processing_stage = Notebook.STAGE_QUESTIONS
            notebook.save(update_fields=['processing_stage'])

        if notebook.processing_stage < Notebook.STAGE_READY:
            notebook.status = Notebook.STATUS_READY
            notebook.processing_stage = Notebook.STAGE_READY
            notebook.save(update_fields=['status', 'processing_stage'])

    except Exception as exc:
        logger.exception('Error processing notebook %s', notebook_id)
        try:
            notebook = Notebook.objects.get(pk=notebook_id)
            notebook.status = Notebook.STATUS_ERROR
            notebook.error_message = ai_service.friendly_error(exc)
            notebook.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
    finally:
        connection.close()


# ────────────────────────── Dashboard ──────────────────────────

@login_required
def dashboard(request):
    notebooks = Notebook.objects.filter(user=request.user).prefetch_related('questions')
    q = request.GET.get('q', '').strip()
    if q:
        notebooks = notebooks.filter(Q(title__icontains=q) | Q(description__icontains=q))
    return render(
        request,
        'notebooks/dashboard.html',
        {'notebooks': notebooks, 'search_q': q},
    )


# ────────────────────────── Upload ──────────────────────────

@login_required
@require_POST
def retry_processing(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    if notebook.status != Notebook.STATUS_ERROR:
        return redirect('notebooks:processing', pk=pk)
    notebook.status = Notebook.STATUS_PROCESSING
    notebook.error_message = ''
    notebook.save(update_fields=['status', 'error_message'])
    thread = threading.Thread(target=_process_notebook, args=(notebook.pk,), daemon=True)
    thread.start()
    return redirect('notebooks:processing', pk=pk)


@login_required
def upload_pdf(request):
    if request.method == 'POST':
        form = PDFUploadForm(request.POST, request.FILES)
        if form.is_valid():
            notebook = form.save(commit=False)
            notebook.user = request.user
            notebook.status = Notebook.STATUS_UPLOADING
            notebook.save()

            # Kick off background processing
            thread = threading.Thread(
                target=_process_notebook,
                args=(notebook.pk,),
                daemon=True,
            )
            thread.start()

            return redirect('notebooks:processing', pk=notebook.pk)
        else:
            messages.error(request, 'Please fix the errors below.')
    else:
        form = PDFUploadForm()
    return render(request, 'notebooks/upload.html', {
        'form': form,
        'ocr_available': tesseract_ocr_available(),
    })


# ────────────────────────── Processing / Status ──────────────────────────

@login_required
def notebook_processing(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    if notebook.status == Notebook.STATUS_READY:
        return redirect('notebooks:detail', pk=pk)
    return render(request, 'notebooks/processing.html', {'notebook': notebook})


@login_required
def notebook_status(request, pk):
    """HTMX polling endpoint — when the notebook is ready, respond with HX-Redirect to the detail page."""
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    notebook.refresh_from_db(fields=['status', 'error_message', 'processing_stage'])
    if notebook.is_ready:
        if request.htmx:
            return HttpResponseClientRedirect(reverse('notebooks:detail', args=[pk]))
        return redirect('notebooks:detail', pk=pk)
    resp = render(request, 'notebooks/partials/processing_status.html', {'notebook': notebook})
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


# ────────────────────────── Notebook Detail ──────────────────────────

@login_required
def notebook_detail(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    if not notebook.is_ready:
        return redirect('notebooks:processing', pk=pk)

    questions = notebook.questions.prefetch_related('answer').all()
    summary, _ = Summary.objects.get_or_create(notebook=notebook)

    # Ensure every question has an Answer row
    for q in questions:
        if not hasattr(q, 'answer'):
            Answer.objects.create(question=q)

    profile = getattr(request.user, 'profile', None)
    focus_duration = profile.focus_duration if profile else 25
    break_duration = profile.break_duration if profile else 5

    context = {
        'notebook': notebook,
        'questions': questions,
        'summary': summary,
        'focus_duration': focus_duration,
        'break_duration': break_duration,
    }
    return render(request, 'notebooks/notebook_detail.html', context)


# ────────────────────────── HTMX: Auto-save Notes ──────────────────────────

@login_required
@require_POST
def save_notes(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    fields = ['updated_at']
    if 'notes_content' in request.POST:
        notebook.notes_content = request.POST.get('notes_content', notebook.notes_content)
        fields.append('notes_content')
    if 'notes_html' in request.POST:
        notebook.notes_html = request.POST.get('notes_html', notebook.notes_html)
        fields.append('notes_html')
    notebook.save(update_fields=fields)
    return render(request, 'notebooks/partials/autosave_indicator.html', {'saved': True, 'target': 'notes'})


# ────────────────────────── HTMX: Auto-save Answer ──────────────────────────

@login_required
@require_POST
def save_answer(request, question_pk):
    question = get_object_or_404(Question, pk=question_pk, notebook__user=request.user)
    answer, _ = Answer.objects.get_or_create(question=question)
    answer.user_answer = request.POST.get('user_answer', '')
    # Reset grade when answer changes
    if answer.grade != Answer.GRADE_UNGRADED:
        answer.grade = Answer.GRADE_UNGRADED
        answer.feedback = ''
        answer.graded_at = None
    answer.save()
    return render(request, 'notebooks/partials/autosave_indicator.html', {'saved': True, 'target': f'answer-{question_pk}'})


# ────────────────────────── HTMX: Grade All Answers ──────────────────────────

@login_required
@require_POST
def grade_answers(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    questions = notebook.questions.prefetch_related('answer').all()

    graded = []
    for question in questions:
        answer = getattr(question, 'answer', None)
        if answer is None:
            continue
        if not answer.user_answer.strip():
            answer.grade = Answer.GRADE_INCORRECT
            answer.feedback = 'No answer provided.'
            answer.graded_at = timezone.now()
            answer.save()
            graded.append((question, answer))
            continue

        try:
            result = ai_service.grade_answer(
                question_text=question.question_text,
                expected_answer=question.expected_answer,
                expected_keywords=question.expected_keywords,
                user_answer=answer.user_answer,
            )
            answer.grade = result['grade']
            answer.feedback = result['feedback']
            answer.graded_at = timezone.now()
            answer.save()
        except Exception as exc:
            logger.exception('Error grading question %s', question.pk)
            answer.grade = Answer.GRADE_UNGRADED
            answer.feedback = f'Grading failed: {ai_service.friendly_error(exc)}'
            answer.save()
        graded.append((question, answer))

    return render(request, 'notebooks/partials/grade_results.html', {
        'graded': graded,
        'notebook': notebook,
    })


# ────────────────────────── HTMX: Summary Auto-save ──────────────────────────

@login_required
@require_POST
def save_summary(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    summary, _ = Summary.objects.get_or_create(notebook=notebook)
    summary.user_summary = request.POST.get('user_summary', '')
    summary.save(update_fields=['user_summary'])
    return render(request, 'notebooks/partials/autosave_indicator.html', {'saved': True, 'target': 'summary'})


# ────────────────────────── HTMX: Summary Feedback ──────────────────────────

@login_required
@require_POST
def summary_feedback(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    summary, _ = Summary.objects.get_or_create(notebook=notebook)
    summary.user_summary = request.POST.get('user_summary', summary.user_summary)
    summary.save(update_fields=['user_summary'])

    try:
        result = ai_service.evaluate_summary(
            pdf_text=notebook.pdf_text,
            key_points=summary.key_points,
            user_summary=summary.user_summary,
        )
        summary.included_key_points = result['included_points']
        summary.missed_key_points = result['missed_points']
        summary.feedback_text = result['feedback_text']
        summary.feedback_generated_at = timezone.now()
        summary.save()
    except Exception as exc:
        logger.exception('Error evaluating summary for notebook %s', pk)
        return render(request, 'notebooks/partials/summary_feedback.html', {
            'error': ai_service.friendly_error(exc),
            'summary': summary,
        })

    return render(request, 'notebooks/partials/summary_feedback.html', {'summary': summary})


# ────────────────────────── Study Sessions ──────────────────────────

@login_required
@require_POST
def log_study_session(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    try:
        cycles = int(request.POST.get('cycles_completed', 0))
        focus = int(request.POST.get('focus_duration', 25))
        brk = int(request.POST.get('break_duration', 5))
    except (ValueError, TypeError):
        cycles, focus, brk = 0, 25, 5

    StudySession.objects.create(
        notebook=notebook,
        focus_duration=focus,
        break_duration=brk,
        cycles_completed=cycles,
        ended_at=timezone.now(),
    )
    return HttpResponse(status=204)


# ────────────────────────── Delete Notebook ──────────────────────────

@login_required
@require_POST
def delete_notebook(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    notebook.delete()
    messages.success(request, f'"{notebook.title}" has been deleted.')
    return redirect('notebooks:dashboard')


# ────────────────────────── Generate Notes Summary ──────────────────────────

@login_required
@require_POST
def generate_notes_summary(request, pk):
    """Generate an AI summary of the study notes."""
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    summary, _ = Summary.objects.get_or_create(notebook=notebook)
    
    try:
        if not summary.ai_summary:
            summary.ai_summary = ai_service.generate_notes_summary(notebook.pdf_text)
            summary.save(update_fields=['ai_summary'])
        
        return render(request, 'notebooks/partials/notes_summary.html', {
            'summary': summary,
            'notebook': notebook,
        })
    except Exception as exc:
        logger.exception('Error generating notes summary for notebook %s', pk)
        return render(request, 'notebooks/partials/notes_summary.html', {
            'error': ai_service.friendly_error(exc),
            'summary': summary,
            'notebook': notebook,
        })


# ────────────────────────── Generate Audio Summary ──────────────────────────

@login_required
@require_POST
def generate_audio_summary(request, pk):
    """Generate an audio TTS summary of the study material."""
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    summary, _ = Summary.objects.get_or_create(notebook=notebook)
    
    try:
        # Use existing AI summary or notes content
        text_to_convert = summary.ai_summary or notebook.notes_content or notebook.pdf_text
        
        if not text_to_convert.strip():
            return JsonResponse({
                'error': 'No content available to convert to audio.',
                'success': False
            }, status=400)
        
        # Generate audio using OpenAI TTS
        audio_bytes = ai_service.generate_audio_summary(text_to_convert)
        
        # Save audio to file
        import os
        from django.conf import settings
        audio_dir = os.path.join(settings.MEDIA_ROOT, 'audio')
        os.makedirs(audio_dir, exist_ok=True)
        
        audio_filename = f'summary_{notebook.pk}_{int(timezone.now().timestamp())}.mp3'
        audio_path = os.path.join(audio_dir, audio_filename)
        
        # Write audio content
        with open(audio_path, 'wb') as f:
            f.write(audio_bytes)
        
        audio_file = f'audio/{audio_filename}'
        summary.audio_file = audio_file
        summary.save(update_fields=['audio_file'])
        
        return JsonResponse({
            'success': True,
            'audio_url': f'{settings.MEDIA_URL}{audio_file}',
            'message': 'Audio summary generated successfully!'
        })
        
    except Exception as exc:
        logger.exception('Error generating audio summary for notebook %s', pk)
        return JsonResponse({
            'error': ai_service.friendly_error(exc),
            'success': False
        }, status=500)


# ── Question flagging ──────────────────────────────────────────

@login_required
@require_POST
def toggle_flag_question(request, question_pk):
    question = get_object_or_404(Question, pk=question_pk, notebook__user=request.user)
    question.needs_review = not question.needs_review
    question.save(update_fields=['needs_review'])
    return JsonResponse({'needs_review': question.needs_review})


# ── Anki export ────────────────────────────────────────────────

@login_required
def export_anki(request, pk):
    import random
    import tempfile
    import os
    try:
        import genanki
    except ImportError:
        return HttpResponse('genanki is not installed.', status=500)

    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    questions = notebook.questions.all()

    model_id = random.randrange(1 << 30, 1 << 31)
    deck_id = random.randrange(1 << 30, 1 << 31)

    model = genanki.Model(
        model_id,
        'Cornote Basic',
        fields=[{'name': 'Question'}, {'name': 'Answer'}],
        templates=[{
            'name': 'Card 1',
            'qfmt': '{{Question}}',
            'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}',
        }],
    )

    deck = genanki.Deck(deck_id, notebook.title)
    for q in questions:
        note = genanki.Note(
            model=model,
            fields=[q.question_text, q.expected_answer or ''],
        )
        deck.add_note(note)

    with tempfile.NamedTemporaryFile(suffix='.apkg', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        genanki.Package(deck).write_to_file(tmp_path)
        with open(tmp_path, 'rb') as f:
            data = f.read()
    finally:
        os.unlink(tmp_path)

    safe_title = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in notebook.title)
    response = HttpResponse(data, content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{safe_title}.apkg"'
    return response
