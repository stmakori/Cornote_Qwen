from django.urls import path
from . import views, views_features

app_name = 'notebooks'

urlpatterns = [
    # ────────────── CORE FEATURES ──────────────
    path('', views.dashboard, name='dashboard'),
    path('upload/', views.upload_pdf, name='upload'),
    path('<int:pk>/processing/', views.notebook_processing, name='processing'),
    path('<int:pk>/status/', views.notebook_status, name='status'),
    path('<int:pk>/', views.notebook_detail, name='detail'),
    path('<int:pk>/save-notes/', views.save_notes, name='save_notes'),
    path('<int:pk>/reformat-notes/', views.reformat_notes, name='reformat_notes'),
    path('<int:pk>/save-summary/', views.save_summary, name='save_summary'),
    path('<int:pk>/grade/', views.grade_answers, name='grade_answers'),
    path('<int:pk>/summary-feedback/', views.summary_feedback, name='summary_feedback'),
    path('<int:pk>/notes-summary/', views.generate_notes_summary, name='notes_summary'),
    path('<int:pk>/audio-summary/', views.generate_audio_summary, name='audio_summary'),
    path('<int:pk>/log-session/', views.log_study_session, name='log_session'),
    path('<int:pk>/delete/', views.delete_notebook, name='delete'),
    path('<int:pk>/retry/', views.retry_processing, name='retry'),
    path('<int:pk>/export-pdf/', views_features.export_notebook_pdf, name='export_pdf'),
    path('<int:notebook_id>/exam/', views_features.exam_page, name='exam_page'),
    path('answer/<int:question_pk>/save/', views.save_answer, name='save_answer'),
    path('answer/<int:question_pk>/flag/', views.toggle_flag_question, name='flag_question'),
    path('<int:pk>/export-anki/', views.export_anki, name='export_anki'),

    # ────────────── FEATURE PAGES (HTML) ──────────────
    path('analytics/', views_features.analytics_page, name='analytics_page'),
    path('achievements/', views_features.achievements_page, name='achievements_page'),
    path('preferences/', views_features.preferences_page, name='preferences_page'),
    path('review/', views_features.spaced_review_page, name='spaced_review_page'),
    path('groups/', views_features.study_groups_page, name='study_groups_page'),
    path('groups/join/', views_features.join_group, name='join_group'),
    path('groups/<int:group_id>/', views_features.study_group_detail_page, name='study_group_detail_page'),
    path('groups/<int:group_id>/leave/', views_features.leave_group, name='leave_group'),
    path('teacher/', views_features.teacher_dashboard_page, name='teacher_dashboard_page'),
    path('teacher/classes/create/', views_features.create_class_view, name='create_class'),
    path('teacher/classes/<int:class_id>/', views_features.teacher_class_detail, name='teacher_class_detail'),
    path('teacher/classes/join/', views_features.join_class_view, name='join_class'),
    path('exams/<int:exam_id>/result/', views_features.exam_result_page, name='exam_result_page'),

    # ────────────── FEATURE 1: ANALYTICS API ──────────────
    path('api/analytics/', views_features.analytics_dashboard, name='analytics'),

    # ────────────── FEATURE 2: SPACED REPETITION API ──────────────
    path('api/spaced-repetition/queue/', views_features.spaced_repetition_queue, name='sr_queue'),
    path('api/spaced-repetition/<int:question_id>/review/', views_features.record_review, name='sr_review'),

    # ────────────── FEATURE 8: ACHIEVEMENTS API ──────────────
    path('api/achievements/', views_features.user_achievements, name='achievements'),
    path('api/achievements/check/', views_features.check_achievements, name='check_achievements'),

    # ────────────── FEATURE 9: STUDY GROUPS API ──────────────
    path('api/study-groups/', views_features.user_study_groups, name='my_groups'),
    path('api/study-groups/create/', views_features.create_study_group, name='create_group'),
    path('api/study-groups/<int:group_id>/comments/', views_features.group_comments, name='group_comments'),
    path('api/study-groups/<int:group_id>/add-comment/', views_features.add_group_comment, name='add_comment'),

    # ────────────── FEATURE 10: NOTIFICATIONS API ──────────────
    path('api/notifications/', views_features.user_notifications, name='notifications'),
    path('api/notifications/<int:notification_id>/read/', views_features.mark_notification_read, name='read_notification'),

    # ────────────── FEATURE 12: EXAM API ──────────────
    path('api/exams/<int:notebook_id>/start/', views_features.start_exam_session, name='start_exam'),
    path('api/exams/<int:exam_id>/end/', views_features.end_exam_session, name='end_exam'),
    path('api/exams/<int:exam_id>/report/', views_features.exam_report, name='exam_report'),

    # ────────────── FEATURE 13: LEARNING PATHS API ──────────────
    path('api/learning-paths/<int:notebook_id>/generate/', views_features.generate_learning_path, name='gen_path'),
    path('api/learning-paths/<int:notebook_id>/status/', views_features.learning_path_status, name='path_status'),
    path('api/learning-paths/<int:notebook_id>/advance/', views_features.advance_learning_path, name='advance_path'),

    # ────────────── FEATURE 14: USER PREFERENCES API ──────────────
    path('api/preferences/', views_features.user_preferences, name='preferences'),
    path('api/preferences/update/', views_features.update_preferences, name='update_prefs'),
    path('api/preferences/theme/', views_features.update_theme, name='update_theme'),
]
