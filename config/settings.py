"""
Django settings for Bitcheck / ProofChain AI.

Stack: Django 6, DRF, Celery + Redis, PostgreSQL.
Config loaded from .env via python-decouple.
"""

import os
from pathlib import Path
from decouple import config, Csv
from dotenv import load_dotenv
import dj_database_url

# ============================================================
# Paths
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent

# Always load project-root .env (cwd-independent — running from another folder
# silently skipped .env before, so flags like SQUAD_VA_DEV_MOCK never applied).
load_dotenv(BASE_DIR / '.env')


def _env_truthy(name: str, *, default: bool = False) -> bool:
    """Parse common truthy strings; works after load_dotenv populates os.environ."""
    default_s = 'true' if default else 'false'
    raw = os.environ.get(name)
    if raw is None:
        raw = config(name, default=default_s)
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')

# ============================================================
# Security
# ============================================================
SECRET_KEY = config('SECRET_KEY')
#  Iv deleted staticfile, add collectstatic to our dockerfile, ensuring it will run when clour run notices a change on github
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())


# ============================================================
# Application definition
# ============================================================
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'corsheaders',
    'drf_spectacular',
]

LOCAL_APPS = [
    'apps.core',
    'apps.accounts',
    'apps.billing',
    'apps.bits',
    'apps.api_keys',
    'apps.connectors',
    'apps.verifications',
    'apps.usage',
    'apps.webhooks',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# ============================================================
# Middleware
# ============================================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.core.middleware.RequestLoggingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ============================================================
# URL / WSGI / ASGI
# ============================================================
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# ============================================================
# Templates
# ============================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


# ============================================================
# Database — uses DATABASE_URL, falls back to SQLite
# Examples:
#   PostgreSQL: DATABASE_URL=postgres://user:pass@localhost:5432/bitcheck
#   SQLite:     DATABASE_URL=sqlite:///path/to/db.sqlite3
#   (or omit DATABASE_URL entirely to use SQLite)
# ============================================================
_SQLITE_DEFAULT = f'sqlite:///{BASE_DIR / "db.sqlite3"}'

DATABASES = {
    'default': dj_database_url.config(
        default=_SQLITE_DEFAULT,
        conn_max_age=600,
        conn_health_checks=True,
    )
}


# ============================================================
# Custom User Model — MUST be set before first migration
# ============================================================
AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.EmailBackend',
]


# ============================================================
# Password validation
# ============================================================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ============================================================
# Internationalization
# ============================================================
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ============================================================
# Static files — served by WhiteNoise in production
# ============================================================
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'staticfiles': {
        # Non-manifest storage avoids boot crashes if staticfiles.json is missing/mismatched in the image.
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}


# ============================================================
# Default primary key field type
# ============================================================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ============================================================
# Django REST Framework
# ============================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.accounts.authentication.CsrfExemptSessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user': '120/minute',
    },
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%SZ',
}


# ============================================================
# drf-spectacular — OpenAPI / Swagger
# ============================================================
SPECTACULAR_SETTINGS = {
    'TITLE': 'Bitcheck AI API',
    'DESCRIPTION': 'Multi-modal AI verification platform — backend API.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SCHEMA_PATH_PREFIX': '/api/',
    'COMPONENT_SPLIT_REQUEST': True,
}


# ============================================================
# CORS — allow the Next.js frontend
# ============================================================
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000',
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True  # needed for session cookies


# ============================================================
# Session — DB-backed (simplest for hackathon)
# ============================================================
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # 1 week
SESSION_COOKIE_HTTPONLY = True
# Dev (HTTP): Lax + False. Prod (HTTPS): set Lax/None + True in .env
SESSION_COOKIE_SAMESITE = config('SESSION_COOKIE_SAMESITE', default='Lax')
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
CSRF_COOKIE_SAMESITE = config('CSRF_COOKIE_SAMESITE', default='Lax')
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=False, cast=bool)
# When frontend is on a different port in dev, cookies need this:
CSRF_TRUSTED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000',
    cast=Csv(),
)


# ============================================================
# Celery — Redis broker
# ============================================================
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 min hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 min soft limit
CELERY_BEAT_SCHEDULE = {
    'subscription-rollover': {
        'task': 'apps.billing.tasks.process_subscription_rollovers',
        'schedule': 3600,  # every hour
    },
    'webhook-retry': {
        'task': 'apps.webhooks.tasks.retry_failed_webhooks',
        'schedule': 21600,  # every 6 hours
    },
}


# ============================================================
# Bitcheck — Token Economy
# ============================================================
# ₦100 = 1 bit token. This rate is snapshotted per top-up.
BITCHECK_NAIRA_PER_BIT = config('BITCHECK_NAIRA_PER_BIT', default=100, cast=int)

# Per-modality verification costs in bit tokens
BITCHECK_VERIFICATION_COSTS = {
    'text': 1,
    'image': 2,
    'document': 3,
    'audio': 5,
    'video': 8,
}


# ============================================================
# Connectors (Gmail, Slack, Telegram, …)
# ============================================================
CONNECTOR_CREDENTIALS_KEY = config(
    'CONNECTOR_CREDENTIALS_KEY',
    default='YLuDPrZbz0GWCzAYnnTZaf6Vu0TG3uRbmtdQhTnSzMk=',
)
CONNECTORS_PUBLIC_BASE_URL = config(
    'CONNECTORS_PUBLIC_BASE_URL',
    default='http://localhost:8000',
)

# Deep links in outbound emails / Telegram (consumer app origin)
FRONTEND_APP_BASE_URL = config('FRONTEND_APP_BASE_URL', default='http://localhost:3000').rstrip('/')
CONNECTORS_OAUTH_STATE_SECRET = config(
    'CONNECTORS_OAUTH_STATE_SECRET',
    default=SECRET_KEY,
)
CONNECTORS_DEFAULT_RATE_LIMIT_PER_INSTALL = config(
    'CONNECTORS_DEFAULT_RATE_LIMIT_PER_INSTALL',
    default=60,
    cast=int,
)
CONNECTORS_DEFAULT_RATE_LIMIT_PER_TYPE = config(
    'CONNECTORS_DEFAULT_RATE_LIMIT_PER_TYPE',
    default=1000,
    cast=int,
)

# Telegram (shared bot webhook + deep links)
TELEGRAM_SHARED_BOT_TOKEN = config('TELEGRAM_SHARED_BOT_TOKEN', default='')
TELEGRAM_SHARED_BOT_SECRET = config('TELEGRAM_SHARED_BOT_SECRET', default='')
TELEGRAM_SHARED_BOT_USERNAME = config(
    'TELEGRAM_SHARED_BOT_USERNAME',
    default='BitcheckBot',
).strip().lstrip('@')

# Google OAuth (Gmail connector install)
GOOGLE_OAUTH_CLIENT_ID = config('GOOGLE_OAUTH_CLIENT_ID', default='').strip()
GOOGLE_OAUTH_CLIENT_SECRET = config('GOOGLE_OAUTH_CLIENT_SECRET', default='').strip()
GOOGLE_OAUTH_REDIRECT_URI = config(
    'GOOGLE_OAUTH_REDIRECT_URI',
    default='http://localhost:8000/api/connectors/oauth/gmail/callback/',
).strip()

_REDIS_CACHE_URL = config('REDIS_CACHE_URL', default='')
if _REDIS_CACHE_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _REDIS_CACHE_URL,
        },
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        },
    }


# ============================================================
# Google OAuth
# ============================================================
GOOGLE_CLIENT_ID = config('GOOGLE_CLIENT_ID', default='')


# ============================================================
# Squad Payment Gateway
# ============================================================
SQUAD_SECRET_KEY = config('SQUAD_SECRET_KEY', default='').strip()
SQUAD_WEBHOOK_SECRET = config('SQUAD_WEBHOOK_SECRET', default='').strip()
SQUAD_BASE_URL = config('SQUAD_BASE_URL', default='https://sandbox-api-d.squadco.com').strip().rstrip('/')
# Skip Squad API and create a local VA row (demos when B2B VA is not profiled). Never enable in production.
SQUAD_VA_DEV_MOCK = _env_truthy('SQUAD_VA_DEV_MOCK', default=False)
# Skip Squad checkout and return a mock URL (demos when sandbox returns 403). Never enable in production.
SQUAD_CHECKOUT_DEV_MOCK = _env_truthy('SQUAD_CHECKOUT_DEV_MOCK', default=False)


# ============================================================
# ML / FastAPI Service
# ============================================================
ML_SERVICE_BASE_URL = config('ML_SERVICE_BASE_URL', default='http://localhost:8001')


# ============================================================
# Object Storage (S3-compatible) — stubs
# ============================================================
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='bitcheck-uploads')
AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL', default='')
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='us-east-1')


# ============================================================
# API Key Security
# ============================================================
API_KEY_PEPPER = config('API_KEY_PEPPER', default='change-this-pepper-in-production')
