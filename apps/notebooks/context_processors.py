from .models import UserPreferences


def user_theme(request):
    theme = 'dark'
    if request.user.is_authenticated:
        try:
            prefs = UserPreferences.objects.get(user=request.user)
            if prefs.theme in ('light', 'dark', 'auto'):
                theme = prefs.theme
        except UserPreferences.DoesNotExist:
            pass
    return {'user_theme': theme}
