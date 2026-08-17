import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RAAI.settings')

app = Celery('RAAI')

# Load Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

app.conf.broker_url = 'redis://127.0.0.1:6379/0'
app.conf.result_backend = 'redis://127.0.0.1:6379/0'

print("BROKER:", app.conf.broker_url)