"""
Celery application for Bitcheck / ProofChain AI.

Loaded from apps.accounts.apps.AccountsConfig.ready() after Django setup.
Workers: celery -A config.celery worker -l info
Beat:    celery -A config.celery beat -l info
"""

import os
from celery import Celery

# Set default Django settings module for Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('bitcheck')

# Read config from Django settings, namespace CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps (apps/*/tasks.py)
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Sanity-check task for verifying Celery connectivity."""
    print(f'Request: {self.request!r}')
