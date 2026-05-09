"""
Django settings for Bitcheck / ProofChain AI.

Stack: Django 6, DRF, Celery + Redis, PostgreSQL.
Config loaded from .env via python-decouple.
"""

from pathlib import Path
from decouple import config, Csv

# ============================================================
# Paths
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# Security
# ============================================================
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
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
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.billing',
    'apps.bits',
    'apps.api_keys',
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
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
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
# Database — PostgreSQL (production), SQLite (dev fallback)
# Set DB_ENGINE=django.db.backends.sqlite3 in .env for local dev
# without PostgreSQL.
# ============================================================
_DB_ENGINE = config('DB_ENGINE', default='django.db.backends.postgresql')

if _DB_ENGINE == 'django.db.backends.sqlite3':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='bitcheck'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default='postgres'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
            'OPTIONS': {
                'connect_timeout': 5,
            },
        }
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
# Static files
# ============================================================
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'


# ============================================================
# Default primary key field type
# ============================================================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ============================================================
# Django REST Framework
# ============================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
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
SESSION_COOKIE_SAMESITE = 'Lax'
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
# Google OAuth
# ============================================================
GOOGLE_CLIENT_ID = config('GOOGLE_CLIENT_ID', default='')


# ============================================================
# Squad Payment Gateway
# ============================================================
SQUAD_SECRET_KEY = config('SQUAD_SECRET_KEY', default='')
SQUAD_WEBHOOK_SECRET = config('SQUAD_WEBHOOK_SECRET', default='')
SQUAD_BASE_URL = config('SQUAD_BASE_URL', default='https://sandbox-api-d.squadco.com')


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
