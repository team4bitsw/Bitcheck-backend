"""
WSGI imports `config.wsgi` before `django.setup()` runs. Loading Celery here
pulls Django settings and autodiscovers tasks too early, which can break
Gunicorn/Cloud Run startup. Celery is wired in `apps.accounts.apps` ready().
"""
