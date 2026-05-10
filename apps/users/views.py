from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from .forms import RegisterForm, LoginForm, TimerPreferencesForm
from .models import UserProfile


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
            user = form.get_user()
            login(request, user)
            next_url = request.GET.get('next', 'notebooks:dashboard')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()
    return render(request, 'users/login.html', {'form': form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('users:login')


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
