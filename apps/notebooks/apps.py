from django.apps import AppConfig


class NotebooksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notebooks'

    def ready(self):
        from . import compat
        compat.apply()