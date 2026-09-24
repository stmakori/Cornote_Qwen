from .models import UserPreferences


def user_theme(request):
    theme = 'dark'
    reduce_animations = False
    if request.user.is_authenticated:
        try:
            prefs = UserPreferences.objects.get(user=request.user)
            if prefs.theme in ('light', 'dark', 'auto'):
                theme = prefs.theme
            # base.html adds class="reduce-animations" to <body>; cornote.css uses it
            # as a kill-switch mirroring prefers-reduced-motion.
            reduce_animations = bool(prefs.reduce_animations)
        except UserPreferences.DoesNotExist:
            pass
    return {'user_theme': theme, 'reduce_animations': reduce_animations}
