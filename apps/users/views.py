from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import RegisterForm, LoginForm, TimerPreferencesForm
from .models import UserProfile


def _safe_next_url(request):
    """Return the ``next`` URL from the request if it points back into this
    site, else None. Without this check ``?next=https://evil.example`` would
    make the login page an open redirect."""
    candidate = request.POST.get('next') or request.GET.get('next')
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return candidate
    return None


def register_view(request):
    if request.user.is_authenticated:
        return redirect('notebooks:dashboard')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.create(user=user)
            login(request, user)
            messages.success(request, f'Welcome to Cornote, {user.username}!')
            return redirect('notebooks:dashboard')
    else:
        form = RegisterForm()
    return render(request, 'users/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('notebooks:dashboard')
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(_safe_next_url(request) or 'notebooks:dashboard')
        # Invalid credentials: the form's non_field_errors are rendered inline
        # in the card (see login.html), so no separate flash message is needed.
    else:
        form = LoginForm()
    return render(request, 'users/login.html', {'form': form, 'next': _safe_next_url(request) or ''})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('users:login')


@require_POST
def demo_login_view(request):
    """Log straight into a brand-new, uniquely-seeded demo account - no
    password, no signup - so a hackathon judge can see the whole app
    immediately. Each login creates its own isolated sandbox account (not a
    shared one), so concurrent visitors never stomp on each other's session;
    stale demo accounts are cleaned up automatically after about an hour."""
    from apps.notebooks.services.demo_data import reset_demo_account

    demo_user = reset_demo_account()
    login(request, demo_user, backend='django.contrib.auth.backends.ModelBackend')
    messages.info(request, "You're exploring a temporary demo account - it's discarded after about an hour.")
    return redirect('notebooks:dashboard')


@login_required
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = TimerPreferencesForm(request.POST)
        if form.is_valid():
            profile.focus_duration = form.cleaned_data['focus_duration']
            profile.break_duration = form.cleaned_data['break_duration']
            profile.save()
            messages.success(request, 'Timer preferences saved.')
            return redirect('users:profile')
    else:
        form = TimerPreferencesForm(initial={
            'focus_duration': profile.focus_duration,
            'break_duration': profile.break_duration,
        })
    return render(request, 'users/profile.html', {'form': form, 'profile': profile})
