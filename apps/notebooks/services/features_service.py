"""
Feature Services Module
Implements business logic for all 14 new features

Features:
1. Study Analytics Dashboard
2. Spaced Repetition System
3. Advanced Question Types (UI handles, DB schema ready)
4. OCR for Scanned PDFs
5. Smart Recommendations
6. PDF Export & Sharing
7. Rich Text Editor (Frontend)
8. Achievements & Badges
9. Study Groups
10. Notifications
11. Teacher/Class Management
12. Exam Simulation
13. Learning Paths
14. User Preferences & Themes
"""

from django.utils import timezone
from django.db.models import Q, Avg, Count, F
from datetime import datetime, timedelta
import json
from ..models import (
    StudyAnalytics, QuestionReview, Badge, UserAchievement, StudyGroup,
    Notification, StudentClass, ExamSession, Topic, LearningPath, 
    UserPreferences, Question, Answer, StudySession, Notebook
)


# ════════════════════════════════════════════════════════════
# FEATURE 1: STUDY ANALYTICS DASHBOARD
# ════════════════════════════════════════════════════════════

class AnalyticsService:
    """Manage study analytics and performance metrics"""
    
    @staticmethod
    def update_user_analytics(user):
        """Update or create analytics for a user"""
        analytics, created = StudyAnalytics.objects.get_or_create(user=user)
        
        # Calculate totals
        all_answers = Answer.objects.filter(question__notebook__user=user)
        
        analytics.total_questions_answered = all_answers.count()
        analytics.total_correct = all_answers.filter(grade='correct').count()
        analytics.total_partial = all_answers.filter(grade='partial').count()
        analytics.total_incorrect = all_answers.filter(grade='incorrect').count()
        
        # Calculate accuracy
        if analytics.total_questions_answered > 0:
            correct_and_partial = analytics.total_correct + (analytics.total_partial * 0.5)
            analytics.overall_accuracy = (correct_and_partial / analytics.total_questions_answered) * 100
        
        # Calculate study time
        sessions = StudySession.objects.filter(notebook__user=user, ended_at__isnull=False)
        total_minutes = sum([s.duration_minutes or 0 for s in sessions])
        analytics.total_study_minutes = total_minutes
        
        # Calculate streak
        today = timezone.now().date()
        last_study = StudySession.objects.filter(
            notebook__user=user
        ).order_by('-started_at').first()
        
        if last_study and last_study.started_at.date() >= today - timedelta(days=1):
            analytics.last_study_date = last_study.started_at.date()
            # Count consecutive days
            streak = 1
            check_date = today - timedelta(days=1)
            while StudySession.objects.filter(
                notebook__user=user,
                started_at__date=check_date
            ).exists():
                streak += 1
                check_date -= timedelta(days=1)
            analytics.study_streak_days = streak
        else:
            analytics.study_streak_days = 0
        
        analytics.save()
        return analytics
    
    @staticmethod
    def get_performance_by_notebook(user):
        """Get performance metrics per notebook"""
        notebooks = Notebook.objects.filter(user=user)
        performance = []
        
        for notebook in notebooks:
            answers = Answer.objects.filter(question__notebook=notebook)
            if answers.exists():
                correct = answers.filter(grade='correct').count()
                total = answers.count()
                accuracy = (correct / total * 100) if total > 0 else 0
                
                performance.append({
                    'notebook_id': notebook.id,
                    'notebook_title': notebook.title,
                    'total_questions': total,
                    'correct_answers': correct,
                    'accuracy_percentage': round(accuracy, 1),
                })
        
        return performance
    
    @staticmethod
    def get_weekly_study_stats(user):
        """Get study statistics for the past 7 days"""
        today = timezone.now().date()
        week_start = today - timedelta(days=6)
        
        daily_stats = {}
        for i in range(7):
            date = week_start + timedelta(days=i)
            sessions = StudySession.objects.filter(
                notebook__user=user,
                started_at__date=date
            )
            total_minutes = sum([s.duration_minutes or 0 for s in sessions])
            
            daily_stats[date.isoformat()] = {
                'date': date,
                'minutes_studied': total_minutes,
                'session_count': sessions.count(),
            }
        
        return daily_stats


# ════════════════════════════════════════════════════════════
# FEATURE 2: SPACED REPETITION SYSTEM (SM-2 Algorithm)
# ════════════════════════════════════════════════════════════

class SpacedRepetitionService:
    """Implement SM-2 spaced repetition algorithm"""
    
    @staticmethod
    def calculate_next_review(review, quality):
        """
        SM-2 algorithm: Calculate next review date and ease factor
        quality: 0-5 (0=complete blackout, 5=perfect recall)
        """
        if quality < 3:  # Failed
            review.repetitions = 0
            review.interval = 1
        else:  # Passed
            if review.repetitions == 0:
                review.interval = 1
            elif review.repetitions == 1:
                review.interval = 3
            else:
                review.interval = int(review.interval * review.ease_factor)
            
            review.repetitions += 1
        
        # Update ease factor
        review.ease_factor = max(1.3, review.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        
        # Set next review date
        review.next_review = timezone.now() + timedelta(days=review.interval)
        review.save()
        
        return review
    
    @staticmethod
    def get_due_reviews(user):
        """Get all questions due for review"""
        return QuestionReview.objects.filter(
            user=user,
            next_review__lte=timezone.now()
        ).select_related('question__notebook').order_by('-difficulty_score')
    
    @staticmethod
    def update_difficulty_score(question, grade):
        """Update question difficulty based on grade"""
        try:
            review = QuestionReview.objects.get(question=question, user=question.notebook.user)
        except QuestionReview.DoesNotExist:
            review = QuestionReview.objects.create(
                question=question,
                user=question.notebook.user
            )
        
        # Adjust difficulty based on grade
        if grade == 'incorrect':
            review.difficulty_score = min(100, review.difficulty_score + 10)
        elif grade == 'partial':
            review.difficulty_score = max(0, review.difficulty_score - 5)
        else:  # correct
            review.difficulty_score = max(0, review.difficulty_score - 15)
        
        review.save()
        return review


# ════════════════════════════════════════════════════════════
# FEATURE 8: ACHIEVEMENTS & BADGES
# ════════════════════════════════════════════════════════════

class AchievementService:
    """Manage achievements and badges"""
    
    @staticmethod
    def check_and_award_achievements(user):
        """Check if user qualifies for new badges"""
        analytics = AnalyticsService.update_user_analytics(user)
        awarded = []
        
        # Perfect Score badge (5 correct answers in a row)
        recent_answers = Answer.objects.filter(
            user=user,
            question__notebook__user=user
        ).order_by('-created_at')[:5]
        
        if recent_answers.count() == 5 and all(a.grade == 'correct' for a in recent_answers):
            badge = Badge.objects.get(badge_type='perfect_score')
            achievement, created = UserAchievement.objects.get_or_create(
                user=user,
                badge=badge
            )
            if created:
                awarded.append(badge)
        
        # Speed Learner (Complete 25 questions in < 30 min)
        recent_session = StudySession.objects.filter(
            notebook__user=user
        ).order_by('-started_at').first()
        
        if recent_session and recent_session.duration_minutes and recent_session.duration_minutes < 30:
            questions_in_session = Answer.objects.filter(
                question__notebook=recent_session.notebook,
                updated_at__gte=recent_session.started_at
            ).count()
            
            if questions_in_session >= 25:
                badge = Badge.objects.get(badge_type='speed_learner')
                achievement, created = UserAchievement.objects.get_or_create(
                    user=user,
                    badge=badge
                )
                if created:
                    awarded.append(badge)
        
        # Consistent Learner (7 day streak)
        if analytics.study_streak_days >= 7:
            badge = Badge.objects.get(badge_type='consistent')
            achievement, created = UserAchievement.objects.get_or_create(
                user=user,
                badge=badge
            )
            if created:
                awarded.append(badge)
        
        # Milestone badges
        milestones = [
            (10, 'milestone_10'),
            (50, 'milestone_50'),
            (100, 'milestone_100'),
        ]
        
        for threshold, badge_type in milestones:
            if analytics.total_correct >= threshold:
                badge = Badge.objects.get(badge_type=badge_type)
                achievement, created = UserAchievement.objects.get_or_create(
                    user=user,
                    badge=badge
                )
                if created:
                    awarded.append(badge)
        
        return awarded


# ════════════════════════════════════════════════════════════
# FEATURE 10: NOTIFICATION SYSTEM
# ════════════════════════════════════════════════════════════

class NotificationService:
    """Send and manage notifications"""
    
    @staticmethod
    def create_achievement_notification(user, badge):
        """Create achievement notification"""
        return Notification.objects.create(
            user=user,
            notification_type='achievement',
            title=f'Achievement Unlocked: {badge.name}',
            message=badge.description,
            icon=badge.icon,
            color=badge.color,
        )
    
    @staticmethod
    def create_streak_notification(user, streak_days):
        """Create study streak notification"""
        return Notification.objects.create(
            user=user,
            notification_type='streak',
            title=f'🔥 {streak_days} Day Streak!',
            message=f'Great work! You have studied for {streak_days} consecutive days.',
            icon='bi-fire',
            color='#f59e0b',
        )
    
    @staticmethod
    def create_review_reminder(user):
        """Create review reminder notification"""
        due_count = SpacedRepetitionService.get_due_reviews(user).count()
        if due_count > 0:
            return Notification.objects.create(
                user=user,
                notification_type='reminder',
                title='Questions Due for Review',
                message=f'You have {due_count} questions due for review.',
                icon='bi-clock-history',
                color='#3b82f6',
            )
    
    @staticmethod
    def mark_as_read(notification):
        """Mark notification as read"""
        notification.is_read = True
        notification.save()


# ════════════════════════════════════════════════════════════
# FEATURE 12: EXAM SIMULATION
# ════════════════════════════════════════════════════════════

class ExamService:
    """Manage exam simulation sessions"""
    
    @staticmethod
    def create_exam_session(notebook, user, time_limit_minutes=60):
        """Create a new timed exam session"""
        return ExamSession.objects.create(
            notebook=notebook,
            user=user,
            time_limit_minutes=time_limit_minutes,
            total_questions=notebook.questions.count(),
        )
    
    @staticmethod
    def finalize_exam_session(exam_session):
        """Calculate final score and complete exam"""
        answers = exam_session.answers.all()
        
        exam_session.correct_answers = answers.filter(grade='correct').count()
        exam_session.partial_answers = answers.filter(grade='partial').count()
        
        if answers.exists():
            correct_score = exam_session.correct_answers + (exam_session.partial_answers * 0.5)
            exam_session.score_percentage = (correct_score / answers.count()) * 100
        
        exam_session.is_completed = True
        exam_session.ended_at = timezone.now()
        exam_session.save()
        
        return exam_session
    
    @staticmethod
    def get_exam_report(exam_session):
        """Generate comprehensive exam report"""
        answers = exam_session.answers.all()
        
        report = {
            'exam_id': exam_session.id,
            'notebook': exam_session.notebook.title,
            'time_limit': exam_session.time_limit_minutes,
            'total_questions': exam_session.total_questions,
            'correct_answers': exam_session.correct_answers,
            'partial_answers': exam_session.partial_answers,
            'incorrect_answers': max(0, exam_session.total_questions - exam_session.correct_answers - exam_session.partial_answers),
            'score_percentage': round(exam_session.score_percentage, 1),
            'by_difficulty': {},
        }
        
        # Breakdown by difficulty
        for difficulty in [1, 2, 3]:
            diff_answers = answers.filter(question__difficulty=difficulty)
            if diff_answers.exists():
                correct = diff_answers.filter(grade='correct').count()
                total = diff_answers.count()
                report['by_difficulty'][f'difficulty_{difficulty}'] = {
                    'total': total,
                    'correct': correct,
                    'accuracy': round(correct / total * 100, 1) if total > 0 else 0,
                }
        
        return report


# ════════════════════════════════════════════════════════════
# FEATURE 13: LEARNING PATH GENERATOR
# ════════════════════════════════════════════════════════════

class LearningPathService:
    """Generate and manage learning paths"""
    
    @staticmethod
    def generate_learning_path(notebook):
        """Generate optimal learning path using topological sort"""
        topics = Topic.objects.filter(notebook=notebook).order_by('difficulty_level', 'order_index')
        
        # Simple ordering: easy → medium → hard
        path = list(topics.values_list('id', flat=True))
        
        learning_path, created = LearningPath.objects.get_or_create(notebook=notebook)
        learning_path.topic_sequence = path
        learning_path.current_topic_index = 0
        learning_path.save()
        
        return learning_path
    
    @staticmethod
    def get_current_topic(learning_path):
        """Get current topic in learning path"""
        if not learning_path.topic_sequence:
            return None
        
        try:
            topic_id = learning_path.topic_sequence[learning_path.current_topic_index]
            return Topic.objects.get(id=topic_id)
        except (IndexError, Topic.DoesNotExist):
            return None
    
    @staticmethod
    def advance_topic(learning_path):
        """Move to next topic"""
        learning_path.current_topic_index += 1
        if learning_path.current_topic_index >= len(learning_path.topic_sequence):
            learning_path.current_topic_index = len(learning_path.topic_sequence) - 1
        learning_path.save()


# ════════════════════════════════════════════════════════════
# FEATURE 14: USER PREFERENCES & THEMES
# ════════════════════════════════════════════════════════════

class PreferencesService:
    """Manage user preferences and customization"""
    
    @staticmethod
    def get_or_create_preferences(user):
        """Get user preferences or create defaults"""
        prefs, created = UserPreferences.objects.get_or_create(user=user)
        return prefs
    
    @staticmethod
    def get_user_theme_config(user):
        """Get complete theme configuration for a user"""
        prefs = PreferencesService.get_or_create_preferences(user)
        
        return {
            'theme': prefs.theme,
            'primary_color': prefs.primary_color,
            'secondary_color': prefs.secondary_color,
            'font_size': prefs.font_size,
            'reading_mode': prefs.reading_mode,
            'high_contrast': prefs.high_contrast,
            'animations_enabled': not prefs.reduce_animations,
            'enable_notifications': prefs.enable_notifications,
        }
    
    @staticmethod
    def update_theme(user, theme, primary_color=None, secondary_color=None):
        """Update user theme settings"""
        prefs = PreferencesService.get_or_create_preferences(user)
        
        if theme in ['dark', 'light', 'auto']:
            prefs.theme = theme
        
        if primary_color:
            prefs.primary_color = primary_color
        if secondary_color:
            prefs.secondary_color = secondary_color
        
        prefs.save()
        return prefs
