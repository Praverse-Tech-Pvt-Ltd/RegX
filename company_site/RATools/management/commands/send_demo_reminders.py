"""Send a reminder email ~2 hours before each confirmed demo booking.

Run this periodically (Celery beat, Windows Task Scheduler, or a plain
cron) — every 15-20 minutes is plenty, since the lookup window below is
wide enough to tolerate that cadence without double- or missed-sending
(guarded by DemoRequest.reminder_sent).

    python manage.py send_demo_reminders
"""
from datetime import datetime, timedelta, timezone as py_timezone

from django.conf import settings
from django.core.management.base import BaseCommand

from RATools.models import DemoRequest
from RATools.views import _format_slot_date_label, _format_slot_time_label, _status_update_html
from RATools.graph_email import send_graph_email, GraphNotConfigured

REMINDER_LEAD_HOURS = 2
# How wide a window around "exactly 2h before" counts — must be at least
# as wide as how often this command runs, so no booking falls between runs.
WINDOW_MINUTES = 20


class Command(BaseCommand):
    help = "Email a reminder to visitors whose demo starts in about 2 hours."

    def handle(self, *args, **options):
        now_utc = datetime.now(py_timezone.utc)
        ist = py_timezone(timedelta(hours=5, minutes=30))

        target_start = now_utc + timedelta(hours=REMINDER_LEAD_HOURS)
        window_start = target_start - timedelta(minutes=WINDOW_MINUTES / 2)
        window_end = target_start + timedelta(minutes=WINDOW_MINUTES / 2)

        candidates = DemoRequest.objects.filter(
            status="confirmed", reminder_sent=False,
            slot_date__isnull=False, slot_time__isnull=False,
        )

        sent = 0
        for booking in candidates:
            start_dt = datetime.combine(booking.slot_date, booking.slot_time, tzinfo=ist).astimezone(py_timezone.utc)
            if not (window_start <= start_dt <= window_end):
                continue

            date_label = _format_slot_date_label(start_dt)
            time_label = _format_slot_time_label(start_dt)

            try:
                html = _status_update_html(
                    first_name=booking.first_name or booking.full_name,
                    headline="Your Demo Is Coming Up",
                    message=f"just a reminder — your iPharmaAI demo starts in about {REMINDER_LEAD_HOURS} hours.",
                    date_label=date_label,
                    time_label=time_label,
                )
                send_graph_email(
                    to_email=booking.email, to_name=booking.full_name,
                    subject=f"Reminder: iPharmaAI Demo today at {time_label} UTC",
                    html=html,
                )
                booking.reminder_sent = True
                booking.save(update_fields=["reminder_sent"])
                sent += 1
            except (GraphNotConfigured, Exception) as err:
                self.stderr.write(f"Reminder failed for DemoRequest {booking.id}: {err}")

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} reminder email(s)."))
