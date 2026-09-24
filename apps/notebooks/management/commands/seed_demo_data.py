from django.core.management.base import BaseCommand

from apps.notebooks.services.demo_data import reset_demo_account


class Command(BaseCommand):
    help = 'Create a fresh, uniquely-named demo account with sample notebooks, questions, badges, and a study group.'

    def handle(self, *args, **options):
        demo = reset_demo_account()
        self.stdout.write(self.style.SUCCESS(f'Demo account "{demo.username}" seeded.'))
