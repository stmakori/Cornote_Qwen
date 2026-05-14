import threading

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.notebooks.models import Notebook
from apps.notebooks.views import _process_notebook


class Command(BaseCommand):
    help = (
        'Kick off background processing again for notebooks stuck in '
        '"processing" (e.g. after a server crash). Uses the resumable pipeline.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes',
            type=int,
            default=20,
            help='Only notebooks not updated for this many minutes (default: 20).',
        )

    def handle(self, *args, **options):
        minutes = options['minutes']
        cutoff = timezone.now() - timedelta(minutes=minutes)
        qs = Notebook.objects.filter(
            status=Notebook.STATUS_PROCESSING,
            updated_at__lt=cutoff,
        ).order_by('pk')[:100]
        count = 0
        for nb in qs:
            self.stdout.write(self.style.WARNING(f'Resuming notebook pk={nb.pk} — {nb.title}'))
            thread = threading.Thread(target=_process_notebook, args=(nb.pk,), daemon=True)
            thread.start()
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Started resume threads for {count} notebook(s).'))
