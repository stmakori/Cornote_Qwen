from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views
from .forms import StyledPasswordResetForm, StyledSetPasswordForm

app_name = 'users'

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('demo-login/', views.demo_login_view, name='demo_login'),
    path('profile/', views.profile_view, name='profile'),

    # ── Password reset (Django's built-in views: battle-tested token
    # generation/expiry, we just supply templates matching the app's look) ──
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password_reset.html',
        form_class=StyledPasswordResetForm,
        email_template_name='users/password_reset_email.html',
        subject_template_name='users/password_reset_subject.txt',
        success_url=reverse_lazy('users:password_reset_done'),
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password_reset_done.html',
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password_reset_confirm.html',
        form_class=StyledSetPasswordForm,
        success_url=reverse_lazy('users:password_reset_complete'),
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password_reset_complete.html',
    ), name='password_reset_complete'),
]
