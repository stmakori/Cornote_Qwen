"""
API Views for all 14 new features
Include in main views.py or use as separate blueprint
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.utils import timezone
from django.db.models import Avg, Count
import json
import io


# ════════════════════════════════════════════════════════════
# HTML PAGE VIEWS (render feature templates)
# ════════════════════════════════════════════════════════════

@login_required
def analytics_page(request):
    return render(request, 'notebooks/analytics_dashboard.html')


@login_required
def achievements_page(request):
    return render(request, 'notebooks/achievements.html')


@login_required
def preferences_page(request):
    return render(request, 'notebooks/preferences.html')


# ── Study Groups ──────────────────────────────────────────────

@login_required
def study_groups_page(request):
    from .models import StudyGroup
    my_groups = (
        StudyGroup.objects.filter(members=request.user) |
        StudyGroup.objects.filter(creator=request.user)
    ).distinct().annotate(member_count=Count('members'))
    public_groups = StudyGroup.objects.filter(is_public=True).exclude(
        members=request.user
    ).exclude(creator=request.user).annotate(member_count=Count('members'))[:10]
    return render(request, 'notebooks/study_groups.html', {
        'my_groups': my_groups,
        'public_groups': public_groups,
    })


@login_required
def study_group_detail_page(request, group_id):
    from .models import StudyGroup, GroupComment, Notebook
    group = get_object_or_404(StudyGroup, id=group_id)
    is_member = request.user in group.members.all() or request.user == group.creator
    if not is_member and not group.is_public:
        messages.error(request, 'You are not a member of this group.')
        return redirect('notebooks:study_groups_page')
    comments = GroupComment.objects.filter(study_group=group).select_related(
        'author', 'question__notebook'
    ).order_by('-created_at')[:50]
    notebooks = Notebook.objects.filter(user=request.user, status='ready')
    return render(request, 'notebooks/study_group_detail.html', {
        'group': group,
        'comments': comments,
        'is_member': is_member,
        'notebooks': notebooks,
    })


@login_required
@require_POST
def join_group(request):
    from .models import StudyGroup
    invite_code = request.POST.get('invite_code', '').strip()
    try:
        group = StudyGroup.objects.get(invite_code=invite_code)
    except StudyGroup.DoesNotExist:
        messages.error(request, 'Invalid invite code.')
        return redirect('notebooks:study_groups_page')
    if group.members.count() >= group.max_members:
        messages.error(request, 'This group is full.')
        return redirect('notebooks:study_groups_page')
    group.members.add(request.user)
    messages.success(request, f'Joined "{group.name}"!')
    return redirect('notebooks:study_group_detail_page', group_id=group.id)


@login_required
@require_POST
def leave_group(request, group_id):
    from .models import StudyGroup
    group = get_object_or_404(StudyGroup, id=group_id)
    group.members.remove(request.user)
    messages.success(request, f'Left "{group.name}".')
    return redirect('notebooks:study_groups_page')


# ── Exam Simulation ───────────────────────────────────────────

@login_required
def exam_page(request, notebook_id):
    from .models import Notebook
    notebook = get_object_or_404(Notebook, id=notebook_id, user=request.user)
    if not notebook.is_ready:
        messages.error(request, 'Notebook is not ready yet.')
        return redirect('notebooks:dashboard')
    questions = list(notebook.questions.all())
    return render(request, 'notebooks/exam.html', {
        'notebook': notebook,
        'questions': questions,
        'default_time_limit': 60,
    })


@login_required
def exam_result_page(request, exam_id):
    from .models import ExamSession
    exam = get_object_or_404(ExamSession, id=exam_id, user=request.user)
    from .services.features_service import ExamService
    report = ExamService.get_exam_report(exam)
    return render(request, 'notebooks/exam_result.html', {
        'exam': exam,
        'report': report,
    })


# ── Spaced Repetition ─────────────────────────────────────────

@login_required
def spaced_review_page(request):
    import json
    from .services.features_service import SpacedRepetitionService
    due_reviews = SpacedRepetitionService.get_due_reviews(request.user)
    questions = []
    for review in due_reviews[:20]:
        questions.append({
            'id': review.question.id,
            'review_id': review.id,
            'question_text': review.question.question_text or '',
            'expected_answer': review.question.expected_answer or '',
            'notebook': review.question.notebook.title or '',
            'difficulty': review.difficulty_score,
        })
    return render(request, 'notebooks/spaced_review.html', {
        'questions': questions,
        'questions_json': json.dumps(questions),
        'total_due': due_reviews.count(),
    })


# ── Teacher Dashboard ─────────────────────────────────────────

@login_required
def teacher_dashboard_page(request):
    from .models import StudentClass, TeacherProfile
    profile, _ = TeacherProfile.objects.get_or_create(user=request.user)
    classes = StudentClass.objects.filter(teacher=request.user).annotate(
        student_count=Count('students')
    )
    return render(request, 'notebooks/teacher_dashboard.html', {
        'profile': profile,
        'classes': classes,
    })


@login_required
@require_POST
def create_class_view(request):
    from .models import StudentClass
    name = request.POST.get('name', '').strip()
    subject = request.POST.get('subject', '').strip()
    description = request.POST.get('description', '').strip()
    if not name:
        messages.error(request, 'Class name is required.')
        return redirect('notebooks:teacher_dashboard_page')
    cls = StudentClass.objects.create(
        teacher=request.user,
        name=name,
        subject=subject,
        description=description,
    )
    messages.success(request, f'Class "{cls.name}" created! Invite code: {cls.invite_code}')
    return redirect('notebooks:teacher_class_detail', class_id=cls.id)


@login_required
def teacher_class_detail(request, class_id):
    from .models import StudentClass, Assignment
    cls = get_object_or_404(StudentClass, id=class_id, teacher=request.user)

    if request.method == 'POST' and request.POST.get('action') == 'create_assignment':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        due_date = request.POST.get('due_date', '').strip()
        if title and due_date:
            Assignment.objects.create(
                student_class=cls,
                created_by=request.user,
                title=title,
                description=description,
                due_date=due_date,
            )
            messages.success(request, f'Assignment "{title}" created.')
        else:
            messages.error(request, 'Title and due date are required.')
        return redirect('notebooks:teacher_class_detail', class_id=class_id)

    assignments = cls.assignments.all()
    students = cls.students.all()
    return render(request, 'notebooks/teacher_class_detail.html', {
        'cls': cls,
        'assignments': assignments,
        'students': students,
    })


@login_required
@require_POST
def join_class_view(request):
    from .models import StudentClass
    invite_code = request.POST.get('invite_code', '').strip()
    try:
        cls = StudentClass.objects.get(invite_code=invite_code)
    except StudentClass.DoesNotExist:
        messages.error(request, 'Invalid class invite code.')
        return redirect('notebooks:teacher_dashboard_page')
    cls.students.add(request.user)
    messages.success(request, f'Joined class "{cls.name}"!')
    return redirect('notebooks:teacher_dashboard_page')


# ── PDF Export ────────────────────────────────────────────────

@login_required
def export_notebook_pdf(request, pk):
    from .models import Notebook, Summary
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER

    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    if not notebook.is_ready:
        return HttpResponse('Notebook not ready.', status=400)

    questions = notebook.questions.prefetch_related('answer').all()
    summary, _ = Summary.objects.get_or_create(notebook=notebook)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'],
        fontSize=18, spaceAfter=6, textColor=colors.HexColor('#1e3a5f'))
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
        fontSize=13, spaceBefore=14, spaceAfter=4, textColor=colors.HexColor('#2563eb'))
    body_style = ParagraphStyle('Body', parent=styles['Normal'],
        fontSize=10, spaceAfter=4, leading=14)
    q_style = ParagraphStyle('Q', parent=styles['Normal'],
        fontSize=10, spaceAfter=2, fontName='Helvetica-Bold')
    a_style = ParagraphStyle('A', parent=styles['Normal'],
        fontSize=10, spaceAfter=6, leftIndent=12,
        textColor=colors.HexColor('#334155'))
    fb_style = ParagraphStyle('Fb', parent=styles['Normal'],
        fontSize=9, leftIndent=12, textColor=colors.HexColor('#64748b'))

    story = []
    story.append(Paragraph(notebook.title, title_style))
    story.append(Paragraph(f'Created: {notebook.created_at.strftime("%B %d, %Y")}', body_style))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#e2e8f0')))
    story.append(Spacer(1, 0.3*cm))

    # Key Points
    if summary.key_points:
        story.append(Paragraph('Key Points', h2_style))
        for pt in summary.key_points:
            story.append(Paragraph(f'• {pt}', body_style))
        story.append(Spacer(1, 0.3*cm))

    # Q&A
    story.append(Paragraph('Questions & Answers', h2_style))
    for q in questions:
        story.append(Paragraph(f'Q{q.order_index}: {q.question_text}', q_style))
        ans = getattr(q, 'answer', None)
        if ans and ans.user_answer.strip():
            grade_map = {'correct': '✓ Correct', 'partial': '~ Partial', 'incorrect': '✗ Incorrect', 'ungraded': '- Not graded'}
            grade_label = grade_map.get(ans.grade, ans.grade)
            story.append(Paragraph(f'Your answer: {ans.user_answer}  [{grade_label}]', a_style))
            if ans.feedback:
                story.append(Paragraph(f'Feedback: {ans.feedback}', fb_style))
        else:
            story.append(Paragraph('Your answer: (not answered)', a_style))
        story.append(Spacer(1, 0.1*cm))

    # Summary
    if summary.user_summary:
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph('Your Summary', h2_style))
        story.append(Paragraph(summary.user_summary, body_style))

    doc.build(story)
    buf.seek(0)
    safe_title = "".join(c for c in notebook.title if c.isalnum() or c in ' _-').strip()
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{safe_title}.pdf"'
    return response

from .models import (
    Notebook, Question, Answer, StudyAnalytics, QuestionReview,
    Badge, UserAchievement, StudyGroup, GroupComment, Notification,
    StudentClass, Assignment, ExamSession, Topic, LearningPath, UserPreferences
)
from .services.features_service import (
    AnalyticsService, SpacedRepetitionService, AchievementService,
    NotificationService, ExamService, LearningPathService, PreferencesService
)


# ════════════════════════════════════════════════════════════
# FEATURE 1: STUDY ANALYTICS DASHBOARD
# ════════════════════════════════════════════════════════════

@login_required
@require_GET
def analytics_dashboard(request):
    """Get comprehensive analytics dashboard data"""
    analytics = AnalyticsService.update_user_analytics(request.user)
    performance = AnalyticsService.get_performance_by_notebook(request.user)
    weekly_stats = AnalyticsService.get_weekly_study_stats(request.user)
    
    return JsonResponse({
        'overall': {
            'total_questions': analytics.total_questions_answered,
            'total_correct': analytics.total_correct,
            'total_partial': analytics.total_partial,
            'total_incorrect': analytics.total_incorrect,
            'accuracy_percentage': round(analytics.overall_accuracy, 1),
            'study_minutes': analytics.total_study_minutes,
            'streak_days': analytics.study_streak_days,
            'last_study_date': analytics.last_study_date.isoformat() if analytics.last_study_date else None,
        },
        'by_notebook': performance,
        'weekly': {k: {**v, 'date': v['date'].isoformat()} for k, v in weekly_stats.items()},
    })


# ════════════════════════════════════════════════════════════
# FEATURE 2: SPACED REPETITION SYSTEM
# ════════════════════════════════════════════════════════════

@login_required
@require_GET
def spaced_repetition_queue(request):
    """Get questions due for spaced repetition review"""
    due_reviews = SpacedRepetitionService.get_due_reviews(request.user)
    
    questions = []
    for review in due_reviews[:10]:  # Limit to 10 for one session
        questions.append({
            'question_id': review.question.id,
            'notebook': review.question.notebook.title,
            'question_text': review.question.question_text,
            'difficulty': review.difficulty_score,
            'last_reviewed': review.last_reviewed.isoformat() if review.last_reviewed else None,
        })
    
    return JsonResponse({
        'total_due': due_reviews.count(),
        'questions': questions,
    })


@login_required
@require_POST
def record_review(request, question_id):
    """Record spaced repetition review result"""
    question = get_object_or_404(Question, id=question_id, notebook__user=request.user)
    quality = int(request.POST.get('quality', 3))  # 0-5 rating
    
    try:
        review = QuestionReview.objects.get(question=question, user=request.user)
    except QuestionReview.DoesNotExist:
        review = QuestionReview.objects.create(question=question, user=request.user)
    
    # Calculate next review using SM-2
    review = SpacedRepetitionService.calculate_next_review(review, quality)
    
    return JsonResponse({
        'success': True,
        'next_review': review.next_review.isoformat(),
        'ease_factor': review.ease_factor,
        'interval': review.interval,
    })


# ════════════════════════════════════════════════════════════
# FEATURE 8: GAMIFICATION - ACHIEVEMENTS & BADGES
# ════════════════════════════════════════════════════════════

@login_required
@require_GET
def user_achievements(request):
    """Get all user achievements and badges"""
    achievements = UserAchievement.objects.filter(user=request.user).select_related('badge')
    
    return JsonResponse({
        'total_badges': achievements.count(),
        'badges': [
            {
                'name': a.badge.name,
                'description': a.badge.description,
                'icon': a.badge.icon,
                'color': a.badge.color,
                'earned_at': a.earned_at.isoformat(),
                'badge_type': a.badge.badge_type,
            }
            for a in achievements
        ],
    })


@login_required
@require_POST
def check_achievements(request):
    """Check for new achievements to award"""
    awarded = AchievementService.check_and_award_achievements(request.user)
    
    new_badges = []
    for badge in awarded:
        new_badges.append({
            'name': badge.name,
            'description': badge.description,
            'icon': badge.icon,
            'color': badge.color,
        })
        
        # Create achievement notification
        NotificationService.create_achievement_notification(request.user, badge)
    
    return JsonResponse({
        'new_badges_earned': len(new_badges),
        'badges': new_badges,
    })


# ════════════════════════════════════════════════════════════
# FEATURE 10: NOTIFICATIONS
# ════════════════════════════════════════════════════════════

@login_required
@require_GET
def user_notifications(request):
    """Get user notifications"""
    qs = Notification.objects.filter(user=request.user).order_by('-created_at')
    unread_count = qs.filter(is_read=False).count()
    notifications = qs[:20]
    
    return JsonResponse({
        'unread_count': unread_count,
        'notifications': [
            {
                'id': n.id,
                'type': n.notification_type,
                'title': n.title,
                'message': n.message,
                'icon': n.icon,
                'color': n.color,
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat(),
            }
            for n in notifications
        ],
    })


@login_required
@require_POST
def mark_notification_read(request, notification_id):
    """Mark a notification as read"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    NotificationService.mark_as_read(notification)
    
    return JsonResponse({'success': True})


# ════════════════════════════════════════════════════════════
# FEATURE 12: EXAM SIMULATION MODE
# ════════════════════════════════════════════════════════════

@login_required
@require_POST
def start_exam_session(request, notebook_id):
    """Start a timed exam session"""
    notebook = get_object_or_404(Notebook, id=notebook_id, user=request.user)
    time_limit = int(request.POST.get('time_limit_minutes', 60))
    
    exam = ExamService.create_exam_session(notebook, request.user, time_limit)
    
    return JsonResponse({
        'exam_id': exam.id,
        'time_limit_minutes': exam.time_limit_minutes,
        'total_questions': exam.total_questions,
        'started_at': exam.started_at.isoformat(),
    })


@login_required
@require_POST
def end_exam_session(request, exam_id):
    """End exam session and calculate score"""
    exam = get_object_or_404(ExamSession, id=exam_id, user=request.user)
    exam = ExamService.finalize_exam_session(exam)
    report = ExamService.get_exam_report(exam)
    
    return JsonResponse(report)


@login_required
@require_GET
def exam_report(request, exam_id):
    """Get detailed exam report"""
    exam = get_object_or_404(ExamSession, id=exam_id, user=request.user)
    report = ExamService.get_exam_report(exam)
    
    return JsonResponse(report)


# ════════════════════════════════════════════════════════════
# FEATURE 13: LEARNING PATH SYSTEM
# ════════════════════════════════════════════════════════════

@login_required
@require_POST
def generate_learning_path(request, notebook_id):
    """Generate learning path for a notebook"""
    notebook = get_object_or_404(Notebook, id=notebook_id, user=request.user)
    path = LearningPathService.generate_learning_path(notebook)
    
    return JsonResponse({
        'path_id': path.id,
        'total_topics': len(path.topic_sequence),
        'current_index': path.current_topic_index,
    })


@login_required
@require_GET
def learning_path_status(request, notebook_id):
    """Get current learning path status"""
    notebook = get_object_or_404(Notebook, id=notebook_id, user=request.user)
    
    try:
        path = LearningPath.objects.get(notebook=notebook)
    except LearningPath.DoesNotExist:
        return JsonResponse({'error': 'No learning path created'}, status=404)
    
    current_topic = LearningPathService.get_current_topic(path)
    
    return JsonResponse({
        'current_topic_id': current_topic.id if current_topic else None,
        'current_topic_name': current_topic.name if current_topic else None,
        'progress': {
            'current_index': path.current_topic_index,
            'total_topics': len(path.topic_sequence),
            'percentage': round((path.current_topic_index / len(path.topic_sequence) * 100)) if path.topic_sequence else 0,
        },
    })


@login_required
@require_POST
def advance_learning_path(request, notebook_id):
    """Move to next topic in learning path"""
    notebook = get_object_or_404(Notebook, id=notebook_id, user=request.user)
    
    try:
        path = LearningPath.objects.get(notebook=notebook)
    except LearningPath.DoesNotExist:
        return JsonResponse({'error': 'No learning path found'}, status=404)
    
    LearningPathService.advance_topic(path)
    current_topic = LearningPathService.get_current_topic(path)
    
    return JsonResponse({
        'current_topic_id': current_topic.id if current_topic else None,
        'progress': path.current_topic_index,
    })


# ════════════════════════════════════════════════════════════
# FEATURE 14: USER PREFERENCES & THEMES
# ════════════════════════════════════════════════════════════

@login_required
@require_GET
def user_preferences(request):
    """Get user preferences and theme configuration"""
    config = PreferencesService.get_user_theme_config(request.user)
    
    return JsonResponse(config)


def _to_bool(val):
    """Convert form string values like 'true'/'false' to Python booleans."""
    if isinstance(val, bool):
        return val
    return str(val).lower() in ('true', '1', 'yes', 'on')


@login_required
@require_POST
def update_preferences(request):
    """Update user preferences"""
    prefs = PreferencesService.get_or_create_preferences(request.user)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    valid_themes = {'dark', 'light', 'auto'}
    valid_font_sizes = {'small', 'normal', 'large', 'xlarge'}

    if 'theme' in data and data['theme'] in valid_themes:
        prefs.theme = data['theme']
    if 'font_size' in data and data['font_size'] in valid_font_sizes:
        prefs.font_size = data['font_size']
    if 'primary_color' in data:
        prefs.primary_color = data['primary_color']
    if 'secondary_color' in data:
        prefs.secondary_color = data['secondary_color']
    if 'high_contrast' in data:
        prefs.high_contrast = _to_bool(data['high_contrast'])
    if 'reduce_animations' in data:
        prefs.reduce_animations = _to_bool(data['reduce_animations'])
    if 'reading_mode' in data:
        prefs.reading_mode = _to_bool(data['reading_mode'])
    if 'enable_notifications' in data:
        prefs.enable_notifications = _to_bool(data['enable_notifications'])

    prefs.save()
    return JsonResponse({'success': True, 'message': 'Preferences updated'})


@login_required
@require_POST
def update_theme(request):
    """Update user theme"""
    try:
        data = json.loads(request.body)
    except:
        data = request.POST
    
    theme = data.get('theme')
    primary = data.get('primary_color')
    secondary = data.get('secondary_color')
    
    prefs = PreferencesService.update_theme(request.user, theme, primary, secondary)
    config = PreferencesService.get_user_theme_config(request.user)
    
    return JsonResponse(config)


# ════════════════════════════════════════════════════════════
# FEATURE 9: STUDY GROUPS (Collaboration)
# ════════════════════════════════════════════════════════════

@login_required
@require_GET
def user_study_groups(request):
    """Get user's study groups"""
    groups = StudyGroup.objects.filter(members=request.user) | StudyGroup.objects.filter(creator=request.user)
    groups = groups.distinct()
    
    return JsonResponse({
        'groups': [
            {
                'id': g.id,
                'name': g.name,
                'description': g.description,
                'member_count': g.members.count(),
                'is_creator': g.creator == request.user,
                'is_public': g.is_public,
                'created_at': g.created_at.isoformat(),
            }
            for g in groups
        ]
    })


@login_required
@require_POST
def create_study_group(request):
    """Create a new study group"""
    name = request.POST.get('name', '')
    description = request.POST.get('description', '')
    is_public = request.POST.get('is_public', 'false').lower() == 'true'
    
    group = StudyGroup.objects.create(
        name=name,
        description=description,
        creator=request.user,
        is_public=is_public,
    )
    group.members.add(request.user)
    
    return JsonResponse({
        'id': group.id,
        'name': group.name,
        'invite_code': group.invite_code,
    })


@login_required
@require_GET
def group_comments(request, group_id):
    """Get comments for a study group"""
    group = get_object_or_404(StudyGroup, id=group_id)
    
    # Check if user is member
    if request.user not in group.members.all() and request.user != group.creator:
        return JsonResponse({'error': 'Not a member'}, status=403)
    
    comments = GroupComment.objects.filter(study_group=group).select_related(
        'author', 'question'
    ).order_by('-created_at')

    return JsonResponse({
        'comments': [
            {
                'id': c.id,
                'question_id': c.question.id,
                'question_text': c.question.question_text,
                'author': c.author.username,
                'text': c.content,
                'created_at': c.created_at.isoformat(),
            }
            for c in comments
        ]
    })


@login_required
@require_POST
def add_group_comment(request, group_id):
    """Add comment to group discussion"""
    group = get_object_or_404(StudyGroup, id=group_id)

    if request.user not in group.members.all():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Not a member'}, status=403)
        messages.error(request, 'You are not a member of this group.')
        return redirect('notebooks:study_groups_page')

    question_id = request.POST.get('question_id')
    text = request.POST.get('text', '').strip()

    if not question_id or not text:
        messages.error(request, 'Question and comment text are required.')
        return redirect('notebooks:study_group_detail_page', group_id=group_id)

    question = get_object_or_404(Question, id=question_id)

    comment = GroupComment.objects.create(
        study_group=group,
        question=question,
        author=request.user,
        content=text,
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'id': comment.id,
            'author': comment.author.username,
            'content': comment.content,
            'created_at': comment.created_at.isoformat(),
        })

    return redirect('notebooks:study_group_detail_page', group_id=group_id)
