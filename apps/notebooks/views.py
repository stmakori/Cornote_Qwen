import threading
import logging
from datetime import timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django_htmx.http import HttpResponseClientRedirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Count

from .models import Notebook, Question, Answer, Summary, StudySession, NotebookChatMessage
from .forms import PDFUploadForm, NotesEditForm, SummaryForm
from .services.pdf_processor import truncate_for_ai
from .services.document_processor import extract_document_text, tesseract_ocr_available
from .services import ai_service
from .services import grading
from .services import throttle
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
            try:
                notebook.notes_content = ai_service.format_notes_as_markdown(body)
            except Exception as exc:
                logger.warning('Notes formatting failed for notebook %s: %s', notebook_id, exc)
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
            questions_data = ai_service.generate_questions(
                truncated,
                count=notebook.target_question_count,
            )
            Question.objects.filter(notebook=notebook).delete()
            for idx, q_data in enumerate(questions_data):
                question = Question.objects.create(
                    notebook=notebook,
                    question_text=q_data.get('question_text', ''),
                    question_type=q_data.get('question_type') or Question.QUESTION_TYPE_SHORT_ANSWER,
                    is_math=bool(q_data.get('is_math')),
                    expected_answer=q_data.get('expected_answer', ''),
                    expected_keywords=q_data.get('expected_keywords', []),
                    choices=q_data.get('choices', []),
                    correct_choices=q_data.get('correct_choices', []),
                    matching_pairs=q_data.get('matching_pairs', []),
                    correct_order=q_data.get('correct_order', []),
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
    # Keep the processing URL stable even after a refresh.
    return render(request, 'notebooks/processing.html', {'notebook': notebook})


@login_required
def notebook_status(request, pk):
    """HTMX polling endpoint — when the notebook is ready, respond with HX-Redirect to the detail page."""
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    notebook.refresh_from_db(fields=['status', 'error_message', 'processing_stage'])
    resp = render(request, 'notebooks/partials/processing_status.html', {'notebook': notebook})
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


# ────────────────────────── Notebook Detail ──────────────────────────

@login_required
def notebook_detail(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    # If notebook is still processing, render the processing view inline so
    # reloading the notebook URL doesn't redirect the user to the upload flow.
    if not notebook.is_ready:
        return render(request, 'notebooks/processing.html', {'notebook': notebook})

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

    # Exam mode submits answers through this same endpoint - link them to the
    # exam session (ownership-checked) so exam finalization can find and grade them.
    exam_session_id = request.POST.get('exam_session_id')
    if exam_session_id:
        from .models import ExamSession
        exam_session = ExamSession.objects.filter(pk=exam_session_id, user=request.user).first()
        if exam_session:
            answer.exam_session = exam_session

    answer.save()
    return render(request, 'notebooks/partials/autosave_indicator.html', {'saved': True, 'target': f'answer-{question_pk}'})


# ────────────────────────── HTMX: Get a Hint ──────────────────────────

@login_required
@require_POST
def get_hint(request, question_pk):
    question = get_object_or_404(Question, pk=question_pk, notebook__user=request.user)
    level = int(request.POST.get('level', 1))
    level = 1 if level not in (1, 2) else level

    if throttle.is_throttled(request.user, 'hint', seconds=2):
        return render(request, 'notebooks/partials/hint.html', {
            'question': question, 'hint_text': None, 'level': level,
            'error': 'Slow down a little - one hint request at a time.',
        })

    try:
        hint_text = ai_service.generate_hint(
            question_text=question.question_text,
            expected_answer=question.expected_answer,
            expected_keywords=question.expected_keywords,
            level=level,
        )
        error = None
    except Exception as exc:
        hint_text = None
        error = ai_service.friendly_error(exc)

    return render(request, 'notebooks/partials/hint.html', {
        'question': question,
        'hint_text': hint_text,
        'level': level,
        'error': error,
    })


# ────────────────────────── AI Tutor Chat ──────────────────────────

@login_required
def notebook_chat_page(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    chat_messages = notebook.chat_messages.filter(user=request.user)
    return render(request, 'notebooks/notebook_chat.html', {
        'notebook': notebook,
        'chat_messages': chat_messages,
    })


@login_required
@require_POST
def notebook_chat(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    question = (request.POST.get('message') or '').strip()
    if not question:
        return render(request, 'notebooks/partials/chat_messages.html', {
            'new_messages': [], 'error': 'Type a question first.',
        })

    if throttle.is_throttled(request.user, 'notebook_chat', seconds=2):
        return render(request, 'notebooks/partials/chat_messages.html', {
            'new_messages': [], 'error': 'Slow down a little - one message at a time.',
        })

    source_text = notebook.pdf_text or notebook.notes_content
    history_payload = [
        {'role': m.role, 'content': m.content}
        for m in notebook.chat_messages.filter(user=request.user).order_by('-created_at')[:10][::-1]
    ]

    user_msg = NotebookChatMessage.objects.create(
        notebook=notebook, user=request.user, role=NotebookChatMessage.ROLE_USER, content=question,
    )

    assistant_msg = None
    error = None
    try:
        answer = ai_service.answer_notebook_question(source_text, history_payload, question)
        assistant_msg = NotebookChatMessage.objects.create(
            notebook=notebook, user=request.user, role=NotebookChatMessage.ROLE_ASSISTANT, content=answer,
        )
    except Exception as exc:
        logger.exception('Notebook chat failed for notebook %s', pk)
        error = ai_service.friendly_error(exc)

    return render(request, 'notebooks/partials/chat_messages.html', {
        'new_messages': [m for m in (user_msg, assistant_msg) if m],
        'error': error,
    })


# ────────────────────────── HTMX: Grade All Answers ──────────────────────────

@login_required
@require_POST
def grade_answers(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    questions = notebook.questions.prefetch_related('answer').all()

    results_by_pk = {}  # question.pk -> already-saved answer, in whatever order it was graded
    pending = []  # (question, answer) still needing an AI call

    for question in questions:
        answer = getattr(question, 'answer', None)
        if answer is None:
            continue

        if not answer.user_answer.strip():
            answer.grade = Answer.GRADE_INCORRECT
            expected_keywords_str = ', '.join(question.expected_keywords) if question.expected_keywords else 'N/A'
            answer.feedback = f'No answer provided. Expected concepts: {expected_keywords_str}'
            answer.graded_at = timezone.now()
            answer.save()
            results_by_pk[question.pk] = answer
            continue

        # Multiple choice/true-false/multiple-select/ordering/matching have
        # enough structured data to grade exactly, with zero AI calls - faster,
        # free, and not dependent on the model reading the selection correctly.
        structured = grading.grade_structured_answer(question, answer.user_answer)
        if structured is not None:
            answer.grade = structured['grade']
            answer.feedback = structured['feedback']
            answer.graded_at = timezone.now()
            answer.save()
            results_by_pk[question.pk] = answer
        else:
            pending.append((question, answer))

    # Everything left (short answer / fill-in-the-blank) needs real AI judgment -
    # grade those concurrently instead of one HTTP round-trip at a time.
    if pending:
        items = [
            {
                'question_text': q.question_text,
                'expected_answer': q.expected_answer,
                'expected_keywords': q.expected_keywords,
                'user_answer': a.user_answer,
            }
            for q, a in pending
        ]
        batch_results = ai_service.grade_answer_batch(items)
        for (question, answer), result in zip(pending, batch_results):
            if result['ok']:
                answer.grade = result['grade']
                answer.feedback = result['feedback']
            else:
                logger.warning('Error grading question %s: %s', question.pk, result['error'])
                answer.grade = Answer.GRADE_UNGRADED
                answer.feedback = f"Grading failed: {result['error']}"
            answer.graded_at = timezone.now()
            answer.save()
            results_by_pk[question.pk] = answer

    graded = [(q, results_by_pk[q.pk]) for q in questions if q.pk in results_by_pk]

    # Feed missed questions into the spaced-repetition queue so "review your
    # weak spots" has something real to point at (this service existed but was
    # never actually called anywhere - dead code until now).
    missed_questions = []
    correct_count = 0
    for question, answer in graded:
        if answer.grade in (Answer.GRADE_PARTIAL, Answer.GRADE_INCORRECT):
            SpacedRepetitionService.update_difficulty_score(question, answer.grade)
            missed_questions.append(question)
        elif answer.grade == Answer.GRADE_CORRECT:
            correct_count += 1

    return render(request, 'notebooks/partials/grade_results.html', {
        'graded': graded,
        'notebook': notebook,
        'correct_count': correct_count,
        'missed_count': len(missed_questions),
        'total_graded': len(graded),
    })


# ────────────────────────── Reformat Notes ──────────────────────────

@login_required
@require_POST
def reformat_notes(request, pk):
    """AI-reformat the raw extracted notes into clean structured Markdown."""
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    text = notebook.pdf_text or notebook.notes_content
    if not text.strip():
        return JsonResponse({'error': 'No content to format.'}, status=400)
    if throttle.is_throttled(request.user, 'reformat_notes', seconds=3):
        return JsonResponse({'error': 'Slow down a little - please wait a moment and try again.'}, status=429)
    try:
        formatted = ai_service.format_notes_as_markdown(text)
        notebook.notes_content = formatted
        notebook.notes_html = ''
        notebook.save(update_fields=['notes_content', 'notes_html'])
        return JsonResponse({'success': True, 'notes': formatted})
    except Exception as exc:
        logger.exception('Reformat notes failed for notebook %s', pk)
        return JsonResponse({'error': ai_service.friendly_error(exc)}, status=500)


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

    if throttle.is_throttled(request.user, 'summary_feedback', seconds=3):
        return render(request, 'notebooks/partials/summary_feedback.html', {
            'error': 'Slow down a little - please wait a moment and try again.',
            'summary': summary,
        })

    if not summary.key_points:
        try:
            summary.key_points = ai_service.extract_key_points(notebook.pdf_text or notebook.notes_content)
            summary.save(update_fields=['key_points'])
        except Exception as exc:
            logger.warning('Failed to extract key points dynamically: %s', exc)

    try:
        result = ai_service.evaluate_summary(
            pdf_text=notebook.pdf_text or notebook.notes_content,
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

    if throttle.is_throttled(request.user, 'notes_summary', seconds=3):
        return render(request, 'notebooks/partials/notes_summary.html', {
            'error': 'Slow down a little - please wait a moment and try again.',
            'summary': summary,
            'notebook': notebook,
        })

    try:
        refresh = request.POST.get('refresh') or request.GET.get('refresh')
        # Regenerate if: no summary yet, user requested refresh, or old summary looks truncated
        needs_generation = (
            not summary.ai_summary
            or refresh
            or len(summary.ai_summary) < 300
        )
        if needs_generation:
            source_text = notebook.pdf_text or notebook.notes_content or ''
            if not source_text.strip():
                return render(request, 'notebooks/partials/notes_summary.html', {
                    'error': 'No content available to summarise. Upload a document or add notes first.',
                    'summary': summary,
                    'notebook': notebook,
                })
            new_summary = ai_service.generate_notes_summary(source_text)
            if not new_summary.strip():
                return render(request, 'notebooks/partials/notes_summary.html', {
                    'error': 'The AI could not generate a summary. Please try again.',
                    'summary': summary,
                    'notebook': notebook,
                })
            summary.ai_summary = new_summary
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

    if throttle.is_throttled(request.user, 'audio_summary', seconds=5):
        return JsonResponse({
            'error': 'Slow down a little - please wait a moment and try again.',
            'success': False,
        }, status=429)

    try:
        # Use existing AI summary or notes content
        text_to_convert = summary.ai_summary or notebook.notes_content or notebook.pdf_text
        
        if not text_to_convert.strip():
            return JsonResponse({
                'error': 'No content available to convert to audio.',
                'success': False
            }, status=400)
        
        # Generate audio using the configured TTS path and persist using the real format.
        audio_bytes, audio_ext, audio_content_type = ai_service.generate_audio_summary(text_to_convert)
        
        # Save audio to file
        import os
        from django.conf import settings
        audio_dir = os.path.join(settings.MEDIA_ROOT, 'audio')
        os.makedirs(audio_dir, exist_ok=True)
        
        audio_filename = f'summary_{notebook.pk}_{int(timezone.now().timestamp())}.{audio_ext}'
        audio_path = os.path.join(audio_dir, audio_filename)
        
        # Write audio content
        with open(audio_path, 'wb') as f:
            f.write(audio_bytes)
        
        audio_file = f'audio/{audio_filename}'
        summary.audio_file = audio_file
        summary.save(update_fields=['audio_file'])
        
        return JsonResponse({
            'success': True,
            'audio_url': reverse('notebooks:summary_audio_file', args=[notebook.pk]),
            'audio_content_type': audio_content_type,
            'message': 'Audio summary generated successfully!'
        })
        
    except Exception as exc:
        logger.exception('Error generating audio summary for notebook %s', pk)
        return JsonResponse({
            'error': ai_service.friendly_error(exc),
            'fallback_text': (text_to_convert[:5000] if 'text_to_convert' in locals() else ''),
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


# ────────────────────────── Sharing & gated file access ──────────────────────────
#
# Notebook.is_public / share_token / shared_with existed on the model but had no
# view anywhere that used them - uploaded files (PDFs, generated audio) were only
# ever served via Django's plain media handler, which applies no access control at
# all: anyone with a file's URL could download it, private or not. These views close
# that gap and give the existing sharing fields an actual feature.

def _can_view_notebook(user, notebook, token=None):
    if user.is_authenticated and notebook.user_id == user.pk:
        return True
    if notebook.is_public and token and notebook.share_token and token == notebook.share_token:
        return True
    if user.is_authenticated and notebook.shared_with.filter(pk=user.pk).exists():
        return True
    return False


def serve_notebook_pdf(request, pk):
    """Gated replacement for linking straight to notebook.pdf_file.url."""
    notebook = get_object_or_404(Notebook, pk=pk)
    if not _can_view_notebook(request.user, notebook, token=request.GET.get('token')):
        raise Http404()
    if not notebook.pdf_file:
        raise Http404()
    return FileResponse(
        notebook.pdf_file.open('rb'),
        filename=notebook.pdf_file.name.rsplit('/', 1)[-1],
    )


@login_required
def serve_summary_audio(request, pk):
    """Gated replacement for linking straight to summary.audio_file.url. Audio
    is owner-only for now - the public share view doesn't expose it."""
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    summary = getattr(notebook, 'summary', None)
    if not summary or not summary.audio_file:
        raise Http404()
    return FileResponse(summary.audio_file.open('rb'))


@login_required
@require_POST
def toggle_notebook_sharing(request, pk):
    """Turn public sharing on/off for a notebook. Returns the share URL when enabling."""
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    notebook.is_public = request.POST.get('is_public', 'false').lower() == 'true'
    notebook.save()  # model.save() mints a share_token the first time is_public becomes True
    share_url = None
    if notebook.is_public:
        share_url = request.build_absolute_uri(
            reverse('notebooks:shared_notebook', args=[notebook.share_token])
        )
    return JsonResponse({'is_public': notebook.is_public, 'share_url': share_url})


def shared_notebook_view(request, token):
    """Read-only public view of a notebook shared via its token - no login required.
    Deliberately simple (no grading, no editing, no audio): a study-guide-style
    read-only view of the notes and questions with their model answers."""
    notebook = get_object_or_404(Notebook, share_token=token, is_public=True)
    return render(request, 'notebooks/shared_notebook.html', {
        'notebook': notebook,
        'questions': notebook.questions.all(),
    })
