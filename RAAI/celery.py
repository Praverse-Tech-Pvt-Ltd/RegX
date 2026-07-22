import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RAAI.settings')

app = Celery('RAAI')

# Load Django settings (CELERY_BROKER_URL, CELERY_RESULT_BACKEND,
# CELERY_TASK_ALWAYS_EAGER, etc. come from RAAI/settings.py, which reads
# them from environment variables).
app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()