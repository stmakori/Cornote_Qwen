from django.contrib import admin
from .models import (
    Notebook, Question, Answer, Summary, StudySession,
    # Feature 1: Analytics
    StudyAnalytics,
    # Feature 2: Spaced Repetition
    QuestionReview,
    # Feature 8: Gamification
    Badge, UserAchievement,
    # Feature 9: Study Groups
    StudyGroup, GroupComment,
    # Feature 10: Notifications
    Notification,
    # Feature 11: Teacher Dashboard
    TeacherProfile, StudentClass, Assignment, ClassStatistics,
    # Feature 12: Exam Simulation
    ExamSession,
    # Feature 13: Learning Paths
    Topic, LearningPath,
    # Feature 14: User Preferences
    UserPreferences,
)


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    readonly_fields = ('order_index',)


@admin.register(Notebook)
class NotebookAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'status', 'question_count', 'created_at')
    list_filter = ('status', 'created_at', 'is_public')
    search_fields = ('title', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'share_token')
    inlines = [QuestionInline]

    def question_count(self, obj):
        return obj.questions.count()
    question_count.short_description = 'Questions'


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('notebook', 'order_index', 'question_text', 'question_type', 'difficulty', 'is_math')
    list_filter = ('question_type', 'difficulty', 'is_math', 'notebook')


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ('question', 'user', 'grade', 'graded_at', 'time_spent_seconds')
    list_filter = ('grade', 'graded_at')


@admin.register(Summary)
class SummaryAdmin(admin.ModelAdmin):
    list_display = ('notebook', 'feedback_generated_at')


@admin.register(StudySession)
class StudySessionAdmin(admin.ModelAdmin):
    list_display = ('notebook', 'focus_duration', 'cycles_completed', 'started_at', 'duration_minutes')
    list_filter = ('started_at',)


# ════════════════════════════════════════════════════════════
# FEATURE 1: STUDY ANALYTICS
# ════════════════════════════════════════════════════════════

@admin.register(StudyAnalytics)
class StudyAnalyticsAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_questions_answered', 'overall_accuracy', 'study_streak_days')
    readonly_fields = ('updated_at',)


# ════════════════════════════════════════════════════════════
# FEATURE 2: SPACED REPETITION
# ════════════════════════════════════════════════════════════

@admin.register(QuestionReview)
class QuestionReviewAdmin(admin.ModelAdmin):
    list_display = ('question', 'user', 'next_review', 'ease_factor', 'difficulty_score')
    list_filter = ('ease_factor', 'next_review')
    readonly_fields = ('last_reviewed',)


# ════════════════════════════════════════════════════════════
# FEATURE 8: GAMIFICATION - BADGES
# ════════════════════════════════════════════════════════════

@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'badge_type', 'color')
    search_fields = ('name', 'description')


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ('user', 'badge', 'earned_at', 'progress')
    list_filter = ('badge', 'earned_at')
    readonly_fields = ('earned_at',)


# ════════════════════════════════════════════════════════════
# FEATURE 9: STUDY GROUPS
# ════════════════════════════════════════════════════════════

@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'creator', 'is_public', 'created_at')
    list_filter = ('is_public', 'created_at')
    search_fields = ('name', 'creator__username')
    readonly_fields = ('invite_code', 'created_at', 'updated_at')


@admin.register(GroupComment)
class GroupCommentAdmin(admin.ModelAdmin):
    list_display = ('study_group', 'question', 'author', 'created_at')
    list_filter = ('study_group', 'created_at')
    readonly_fields = ('created_at', 'updated_at')


# ════════════════════════════════════════════════════════════
# FEATURE 10: NOTIFICATIONS
# ════════════════════════════════════════════════════════════

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('user__username', 'title', 'message')
    readonly_fields = ('created_at',)


# ════════════════════════════════════════════════════════════
# FEATURE 11: TEACHER DASHBOARD
# ════════════════════════════════════════════════════════════

@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'subject', 'institution', 'is_verified_teacher')
    list_filter = ('is_verified_teacher',)
    search_fields = ('user__username', 'subject', 'institution')


@admin.register(StudentClass)
class StudentClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'teacher', 'subject', 'created_at')
    list_filter = ('subject', 'created_at')
    search_fields = ('name', 'teacher__username')
    readonly_fields = ('invite_code', 'created_at')


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'student_class', 'due_date', 'created_at')
    list_filter = ('due_date', 'student_class')
    search_fields = ('title', 'student_class__name')


@admin.register(ClassStatistics)
class ClassStatisticsAdmin(admin.ModelAdmin):
    list_display = ('student_class', 'total_students', 'average_accuracy')
    readonly_fields = ('updated_at',)


# ════════════════════════════════════════════════════════════
# FEATURE 12: EXAM SIMULATION
# ════════════════════════════════════════════════════════════

@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ('notebook', 'user', 'score_percentage', 'is_completed', 'started_at')
    list_filter = ('is_completed', 'started_at')
    readonly_fields = ('started_at',)


# ════════════════════════════════════════════════════════════
# FEATURE 13: LEARNING PATHS
# ════════════════════════════════════════════════════════════

@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'notebook', 'difficulty_level', 'order_index')
    list_filter = ('difficulty_level', 'notebook')
    readonly_fields = ('created_at',)


@admin.register(LearningPath)
class LearningPathAdmin(admin.ModelAdmin):
    list_display = ('notebook', 'current_topic_index')
    readonly_fields = ('last_updated',)


# ════════════════════════════════════════════════════════════
# FEATURE 14: USER PREFERENCES
# ════════════════════════════════════════════════════════════

@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme', 'font_size', 'reading_mode', 'enable_notifications')
    list_filter = ('theme', 'font_size', 'reading_mode')
    readonly_fields = ('created_at', 'updated_at')
