from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Notebook(models.Model):
    STATUS_UPLOADING = 'uploading'
    STATUS_PROCESSING = 'processing'
    STATUS_READY = 'ready'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_UPLOADING, 'Uploading'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_READY, 'Ready'),
        (STATUS_ERROR, 'Error'),
    ]

    STAGE_NEW = 0
    STAGE_TEXT = 1
    STAGE_SUMMARY_KEYS = 2
    STAGE_QUESTIONS = 3
    STAGE_READY = 4

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notebooks')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)  # User description
    
    pdf_file = models.FileField(upload_to='documents/%Y/%m/')
    pdf_text = models.TextField(blank=True)
    notes_content = models.TextField(blank=True, help_text='User-edited version of the extracted notes')
    
    # Resumable pipeline: 0=new, 1=text extracted, 2=key points saved, 3=questions saved, 4=ready
    processing_stage = models.PositiveSmallIntegerField(default=0, db_index=True)
    
    # Rich text editor content
    notes_html = models.TextField(blank=True)  # HTML version of notes
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UPLOADING)
    error_message = models.TextField(blank=True)
    
    # OCR & Image extraction
    has_images = models.BooleanField(default=False)
    extracted_images = models.JSONField(default=list)  # List of image paths
    is_scanned_pdf = models.BooleanField(default=False)
    ocr_completed = models.BooleanField(default=False)
    
    # Sharing feature
    is_public = models.BooleanField(default=False, help_text='Allow others to view this notebook')
    share_token = models.CharField(max_length=32, unique=True, blank=True, null=True, db_index=True)
    shared_with = models.ManyToManyField(User, related_name='shared_notebooks', blank=True)
    is_shared_to_group = models.BooleanField(default=False)
    
    # Teacher assignment
    assignment = models.ForeignKey('Assignment', on_delete=models.SET_NULL, null=True, blank=True, related_name='student_notebooks')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['is_public']),
            models.Index(fields=['is_scanned_pdf']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Auto-generate share token if making public
        if self.is_public and not self.share_token:
            import secrets
            self.share_token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    @property
    def is_ready(self):
        return self.status == self.STATUS_READY

    @property
    def source_extension(self) -> str:
        name = (self.pdf_file.name or '').lower()
        if '.' in name:
            return '.' + name.rsplit('.', 1)[-1]
        return ''

    @property
    def is_pdf_embeddable(self) -> bool:
        """Only PDFs can be shown in the in-app iframe viewer."""
        return self.source_extension == '.pdf'

    @property
    def question_count(self):
        return self.questions.count()

    @property
    def answered_count(self):
        return self.questions.filter(answer__user_answer__gt='').count()

    @property
    def graded_count(self):
        return self.questions.exclude(answer__grade='ungraded').count()


class Question(models.Model):
    QUESTION_TYPE_SHORT_ANSWER = 'short_answer'
    QUESTION_TYPE_MULTIPLE_CHOICE = 'multiple_choice'
    QUESTION_TYPE_TRUE_FALSE = 'true_false'
    QUESTION_TYPE_FILL_BLANK = 'fill_blank'
    QUESTION_TYPE_MULTIPLE_SELECT = 'multiple_select'
    QUESTION_TYPE_MATCHING = 'matching'
    QUESTION_TYPE_ORDERING = 'ordering'
    
    QUESTION_TYPE_CHOICES = [
        (QUESTION_TYPE_SHORT_ANSWER, 'Short Answer'),
        (QUESTION_TYPE_MULTIPLE_CHOICE, 'Multiple Choice'),
        (QUESTION_TYPE_TRUE_FALSE, 'True/False'),
        (QUESTION_TYPE_FILL_BLANK, 'Fill in the Blank'),
        (QUESTION_TYPE_MULTIPLE_SELECT, 'Multiple Select'),
        (QUESTION_TYPE_MATCHING, 'Matching Pairs'),
        (QUESTION_TYPE_ORDERING, 'Ordering/Sequence'),
    ]
    
    DIFFICULTY_CHOICES = [
        (1, 'Easy'),
        (2, 'Medium'),
        (3, 'Hard'),
    ]

    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='questions')
    topic = models.ForeignKey('Topic', on_delete=models.SET_NULL, null=True, blank=True, related_name='questions')
    
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES, default=QUESTION_TYPE_SHORT_ANSWER)
    expected_answer = models.TextField(blank=True)
    expected_keywords = models.JSONField(default=list)
    
    # For multiple choice/select questions
    choices = models.JSONField(default=list, blank=True, help_text='List of choices for multiple choice questions')
    correct_choices = models.JSONField(default=list, blank=True)  # For multiple select
    
    # For matching questions
    matching_pairs = models.JSONField(default=list, blank=True)  # [{"left": "...", "right": "..."}]
    
    # For ordering questions
    correct_order = models.JSONField(default=list, blank=True)  # [item1, item2, item3]
    
    # Metadata
    order_index = models.IntegerField(default=0)
    difficulty = models.IntegerField(choices=DIFFICULTY_CHOICES, default=2)
    is_flashcard = models.BooleanField(default=False)
    needs_review = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order_index']
        indexes = [
            models.Index(fields=['notebook', 'order_index']),
            models.Index(fields=['question_type']),
            models.Index(fields=['difficulty']),
        ]

    def __str__(self):
        return f'Q{self.order_index}: {self.question_text[:60]}'

    @property
    def has_answer(self):
        return hasattr(self, 'answer') and bool(self.answer.user_answer.strip())


class Answer(models.Model):
    GRADE_UNGRADED = 'ungraded'
    GRADE_CORRECT = 'correct'
    GRADE_PARTIAL = 'partial'
    GRADE_INCORRECT = 'incorrect'
    GRADE_CHOICES = [
        (GRADE_UNGRADED, 'Not Yet Graded'),
        (GRADE_CORRECT, 'Correct'),
        (GRADE_PARTIAL, 'Partially Correct'),
        (GRADE_INCORRECT, 'Incorrect'),
    ]
    GRADE_BADGE = {
        GRADE_UNGRADED: 'secondary',
        GRADE_CORRECT: 'success',
        GRADE_PARTIAL: 'warning',
        GRADE_INCORRECT: 'danger',
    }

    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name='answer')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='answers', null=True, blank=True)
    
    user_answer = models.TextField(blank=True)
    grade = models.CharField(max_length=20, choices=GRADE_CHOICES, default=GRADE_UNGRADED, db_index=True)
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    
    # For tracking performance
    time_spent_seconds = models.IntegerField(default=0)  # How long user spent on this question
    attempt_count = models.IntegerField(default=1)  # Number of attempts
    
    # For exam sessions
    exam_session = models.ForeignKey('ExamSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='answers')
    
    # For matching/ordering questions
    user_answer_json = models.JSONField(default=dict, blank=True)  # Structured answer format
    
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['grade']),
            models.Index(fields=['user', '-updated_at']),
        ]

    def __str__(self):
        return f'Answer to {self.question}'

    @property
    def badge_color(self):
        return self.GRADE_BADGE.get(self.grade, 'secondary')


class Summary(models.Model):
    notebook = models.OneToOneField(Notebook, on_delete=models.CASCADE, related_name='summary')
    user_summary = models.TextField(blank=True)
    key_points = models.JSONField(default=list, help_text='Key points extracted from the PDF')
    missed_key_points = models.JSONField(default=list)
    included_key_points = models.JSONField(default=list)
    feedback_text = models.TextField(blank=True)
    feedback_generated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ai_summary = models.TextField(blank=True, help_text='AI-generated summary of the material')
    audio_file = models.FileField(upload_to='audio/', blank=True, null=True, help_text='Audio summary MP3 file')

    class Meta:
        indexes = [
            models.Index(fields=['feedback_generated_at']),
        ]

    def __str__(self):
        return f'Summary for {self.notebook.title}'


class StudySession(models.Model):
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='study_sessions')
    focus_duration = models.IntegerField(default=25)
    break_duration = models.IntegerField(default=5)
    cycles_completed = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['notebook', '-started_at']),
            models.Index(fields=['started_at']),
        ]

    def __str__(self):
        return f'Session for {self.notebook.title} at {self.started_at}'

    @property
    def duration_minutes(self):
        if self.ended_at:
            delta = self.ended_at - self.started_at
            return int(delta.total_seconds() / 60)
        return None


# ════════════════════════════════════════════════════════════
# FEATURE 2: SPACED REPETITION SYSTEM
# ════════════════════════════════════════════════════════════

class QuestionReview(models.Model):
    """Track question reviews for spaced repetition algorithm (SM-2)"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # SM-2 algorithm parameters
    interval = models.IntegerField(default=1)  # Days until next review
    ease_factor = models.FloatField(default=2.5)  # Quality factor (1.3-2.5)
    repetitions = models.IntegerField(default=0)  # Number of successful reviews
    
    last_reviewed = models.DateTimeField(auto_now=True, db_index=True)
    next_review = models.DateTimeField(auto_now_add=True, db_index=True)
    difficulty_score = models.IntegerField(default=0)  # 0-100
    
    class Meta:
        unique_together = ('question', 'user')
        indexes = [
            models.Index(fields=['user', 'next_review']),
            models.Index(fields=['difficulty_score']),
        ]

    def __str__(self):
        return f'Review: {self.question} - User {self.user.username}'


# ════════════════════════════════════════════════════════════
# FEATURE 1: STUDY ANALYTICS
# ════════════════════════════════════════════════════════════

class StudyAnalytics(models.Model):
    """Aggregate study statistics for user"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='study_analytics')
    
    # Metrics
    total_questions_answered = models.IntegerField(default=0)
    total_correct = models.IntegerField(default=0)
    total_partial = models.IntegerField(default=0)
    total_incorrect = models.IntegerField(default=0)
    total_study_minutes = models.IntegerField(default=0)
    study_streak_days = models.IntegerField(default=0)
    last_study_date = models.DateField(null=True, blank=True)
    
    # Performance
    overall_accuracy = models.FloatField(default=0.0)  # Percentage 0-100
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Study Analytics"

    def __str__(self):
        return f'Analytics for {self.user.username}'


# ════════════════════════════════════════════════════════════
# FEATURE 8: GAMIFICATION - ACHIEVEMENTS & BADGES
# ════════════════════════════════════════════════════════════

class Badge(models.Model):
    """Achievement badges users can earn"""
    BADGE_TYPES = [
        ('perfect_score', 'Perfect Score'),
        ('speed_learner', 'Speed Learner'),
        ('consistent', 'Consistent Learner'),
        ('master', 'Topic Master'),
        ('comeback', 'Comeback Kid'),
        ('milestone_10', '10 Questions'),
        ('milestone_50', '50 Correct Answers'),
        ('milestone_100', '100 Hours Studied'),
        ('sharing_guru', 'Sharing Guru'),
        ('first_export', 'Documentarian'),
    ]
    
    name = models.CharField(max_length=100)
    badge_type = models.CharField(max_length=20, choices=BADGE_TYPES, unique=True)
    description = models.TextField()
    icon = models.CharField(max_length=50, default='bi-star-fill')  # Bootstrap icon class
    color = models.CharField(max_length=7, default='#fbbf24')  # Hex color
    
    def __str__(self):
        return self.name


class UserAchievement(models.Model):
    """Track badges earned by users"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='achievements')
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    earned_at = models.DateTimeField(auto_now_add=True)
    progress = models.IntegerField(default=0)  # 0-100 for progress-based badges
    
    class Meta:
        unique_together = ('user', 'badge')
        indexes = [
            models.Index(fields=['user', 'earned_at']),
        ]

    def __str__(self):
        return f'{self.user.username} earned {self.badge.name}'


# ════════════════════════════════════════════════════════════
# FEATURE 9: STUDY GROUPS & COLLABORATION
# ════════════════════════════════════════════════════════════

class StudyGroup(models.Model):
    """Groups of students studying together"""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_study_groups')
    members = models.ManyToManyField(User, related_name='study_groups')
    invite_code = models.CharField(max_length=20, unique=True, db_index=True)
    
    is_public = models.BooleanField(default=False)
    max_members = models.IntegerField(default=50)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.invite_code:
            import secrets
            self.invite_code = secrets.token_urlsafe(10)
        super().save(*args, **kwargs)


class GroupComment(models.Model):
    """Comments on questions within a study group"""
    study_group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='comments')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='group_comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['study_group', 'question']),
        ]

    def __str__(self):
        return f'Comment by {self.author.username}'


# ════════════════════════════════════════════════════════════
# FEATURE 10: NOTIFICATIONS
# ════════════════════════════════════════════════════════════

class Notification(models.Model):
    TYPES = [
        ('achievement', 'Achievement Unlocked'),
        ('reminder', 'Study Reminder'),
        ('streak', 'Streak Alert'),
        ('group_invite', 'Group Invitation'),
        ('comment', 'New Comment'),
        ('system', 'System Message'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    icon = models.CharField(max_length=50, default='bi-bell')
    color = models.CharField(max_length=7, default='#3b82f6')
    
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Optional related object
    related_object_id = models.IntegerField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f'{self.title} for {self.user.username}'


# ════════════════════════════════════════════════════════════
# FEATURE 11: TEACHER/CLASS MANAGEMENT
# ════════════════════════════════════════════════════════════

class TeacherProfile(models.Model):
    """Extended profile for teachers"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teacher_profile')
    subject = models.CharField(max_length=255, blank=True)
    institution = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True)
    is_verified_teacher = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Teacher: {self.user.username}'


class StudentClass(models.Model):
    """A class taught by a teacher"""
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='classes')
    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    students = models.ManyToManyField(User, related_name='enrolled_classes', blank=True)
    
    invite_code = models.CharField(max_length=20, unique=True, db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.invite_code:
            import secrets
            self.invite_code = secrets.token_urlsafe(10)
        super().save(*args, **kwargs)


class Assignment(models.Model):
    """Assignment given to a class"""
    student_class = models.ForeignKey(StudentClass, on_delete=models.CASCADE, related_name='assignments')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    title = models.CharField(max_length=255)
    description = models.TextField()
    
    # Questions for this assignment
    questions = models.ManyToManyField(Question, blank=True)
    
    due_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-due_date']

    def __str__(self):
        return self.title


class ClassStatistics(models.Model):
    """Aggregate statistics for a class"""
    student_class = models.OneToOneField(StudentClass, on_delete=models.CASCADE, related_name='statistics')
    
    total_students = models.IntegerField(default=0)
    average_accuracy = models.FloatField(default=0.0)
    most_difficult_topics = models.JSONField(default=list)  # List of topic names
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Class Statistics"

    def __str__(self):
        return f'Statistics for {self.student_class.name}'


# ════════════════════════════════════════════════════════════
# FEATURE 12: EXAM SIMULATION MODE
# ════════════════════════════════════════════════════════════

class ExamSession(models.Model):
    """Timed exam practice sessions"""
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='exam_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    time_limit_minutes = models.IntegerField(default=60)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Results
    total_questions = models.IntegerField(default=0)
    correct_answers = models.IntegerField(default=0)
    partial_answers = models.IntegerField(default=0)
    score_percentage = models.FloatField(default=0.0)
    
    is_completed = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['user', '-started_at']),
        ]

    def __str__(self):
        return f'Exam: {self.notebook.title} - {self.user.username}'


# ════════════════════════════════════════════════════════════
# FEATURE 13: LEARNING PATH GENERATOR
# ════════════════════════════════════════════════════════════

class Topic(models.Model):
    """Learning topics/concepts"""
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='topics')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    difficulty_level = models.IntegerField(default=1)  # 1=easy, 2=medium, 3=hard
    prerequisites = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='dependent_topics')
    
    order_index = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['order_index']

    def __str__(self):
        return self.name


class LearningPath(models.Model):
    """Suggested learning sequence for a notebook"""
    notebook = models.OneToOneField(Notebook, on_delete=models.CASCADE, related_name='learning_path')
    
    # Ordered list of topic IDs
    topic_sequence = models.JSONField(default=list)
    
    # User's progress
    completed_topics = models.JSONField(default=list)
    current_topic_index = models.IntegerField(default=0)
    
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f'Path for {self.notebook.title}'


# ════════════════════════════════════════════════════════════
# FEATURE 14: USER PREFERENCES & THEMES
# ════════════════════════════════════════════════════════════

class UserPreferences(models.Model):
    THEME_CHOICES = [
        ('dark', 'Dark Theme'),
        ('light', 'Light Theme'),
        ('auto', 'Auto (System)'),
    ]
    
    FONT_SIZE_CHOICES = [
        ('small', 'Small'),
        ('normal', 'Normal'),
        ('large', 'Large'),
        ('xlarge', 'Extra Large'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preferences')
    
    # Theme customization
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='dark')
    primary_color = models.CharField(max_length=7, default='#2563eb')  # Hex color
    secondary_color = models.CharField(max_length=7, default='#059669')
    
    # Accessibility
    font_size = models.CharField(max_length=20, choices=FONT_SIZE_CHOICES, default='normal')
    reading_mode = models.BooleanField(default=False)  # Distraction-free mode
    reduce_animations = models.BooleanField(default=False)
    high_contrast = models.BooleanField(default=False)
    
    # Notifications
    enable_notifications = models.BooleanField(default=True)
    daily_reminder = models.BooleanField(default=True)
    reminder_time = models.TimeField(default='09:00')  # When to show daily reminder
    
    # Study preferences
    auto_save_enabled = models.BooleanField(default=True)
    show_keyboard_shortcuts = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "User Preferences"

    def __str__(self):
        return f'Preferences for {self.user.username}'
