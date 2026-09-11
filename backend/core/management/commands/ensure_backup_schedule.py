"""
Idempotently register the daily cloud-backup django-q2 Schedule.

Safe to run on every container boot — it only creates or refreshes one row.
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from django_q.models import Schedule


class Command(BaseCommand):
    help = "Ensure the daily cloud-backup Schedule exists in django-q2."

    def handle(self, *args, **options):
        hook_time = timezone.localtime()
        backup_at = hook_time.replace(hour=23, minute=30, second=0, microsecond=0)
        if backup_at <= hook_time:
            backup_at += timedelta(days=1)

        schedule, created = Schedule.objects.update_or_create(
            name="cloud_backup_daily",
            defaults={
                "func": "core.tasks.run_cloud_backup",
                "schedule_type": Schedule.DAILY,
                "repeats": -1,
                "next_run": backup_at,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS("Created cloud_backup_daily schedule."))
        else:
            self.stdout.write("cloud_backup_daily schedule already exists — refreshed.")