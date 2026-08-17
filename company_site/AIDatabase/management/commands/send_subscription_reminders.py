import os
from datetime import date, timedelta
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from AdminMaster.models import CustomUser

class Command(BaseCommand):
    help = 'Send email alerts for subscriptions expiring in 50 days or less'

    def handle(self, *args, **options):
        self.stdout.write("Checking for subscription renewals expiring in 50 days or less...")

        today = date.today()
        target_date = today + timedelta(days=50)

        # Find active users whose subscription expires in 50 days or less, and who haven't received a reminder
        expiring_users = CustomUser.objects.filter(
            is_active=True,
            subscription_end_date=target_date,
            # reminder_sent_50_days=False
        )
        self.stdout.write(f"Found expiring users: {list(expiring_users)}")

        if not expiring_users.exists():
            self.stdout.write("No subscriptions expiring in 50 days or less found.")
            return

        # Load email lists from .env file using dotenv
        load_dotenv(os.path.join(settings.BASE_DIR, '.env'))
        to_emails_str = os.getenv('REMINDER_TO_EMAILS', 'khushbu@icretegy.com,dhwani@icretegy.com,shubhangi@icretegy.com')
        cc_emails_str = os.getenv('REMINDER_CC_EMAILS', 'jayesh@icretegy.com')

        to_emails = [email.strip() for email in to_emails_str.split(',') if email.strip()]
        cc_emails = [email.strip() for email in cc_emails_str.split(',') if email.strip()]

        for user in expiring_users:
            client_name = user.username or user.company_name
            expiry_date_str = user.subscription_end_date.strftime("%Y-%m-%d")

            subject = f"Client Subscription Expiry Reminder – {client_name}"

            # Text email content
            text_content = (
                f"Hi Team,\n\n"
                f"This is an automated reminder that the subscription/license for {client_name} is scheduled to expire on {expiry_date_str}.\n\n"
                f"Days Remaining: 50 Days\n"
                f"Expiry Date: {expiry_date_str}\n\n"
                f"Kindly initiate the renewal follow-up process with the client to ensure timely renewal and uninterrupted service.\n\n"
                f"Thanks & Regards,\n"
                f"iPharmaAI Renewal Reminder System"
            )

            # HTML email content
            html_content = (
                f"<p>Hi Team,</p>"
                f"<p>This is an automated reminder that the subscription/license for <strong>{client_name}</strong> is scheduled to expire on <strong>{expiry_date_str}</strong>.</p>"
                f"<p><strong>Days Remaining:</strong> 50 Days<br>"
                f"<strong>Expiry Date:</strong> {expiry_date_str}</p>"
                f"<p>Kindly initiate the renewal follow-up process with the client to ensure timely renewal and uninterrupted service.</p>"
                f"<p>Thanks & Regards,<br>"
                f"iPharmaAI Renewal Reminder System</p>"
            )

            try:
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=to_emails,
                    cc=cc_emails,
                )
                email.attach_alternative(html_content, "text/html")
                email.send(fail_silently=False)

                # Mark as sent
                # user.reminder_sent_50_days = True
                # user.save(update_fields=['reminder_sent_50_days'])

                self.stdout.write(self.style.SUCCESS(f"Successfully sent subscription reminder email for user {user.username} (Client: {client_name}) expiring on {expiry_date_str}."))

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to send email for user {user.username}: {str(e)}"))
