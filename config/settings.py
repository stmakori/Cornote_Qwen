from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='unsafe-secret-key-change-me')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'django_htmx',
    'apps.users',
    'apps.notebooks',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Allow embedding same-site resources (like local PDF previews in iframe modals).
X_FRAME_OPTIONS = 'SAMEORIGIN'

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.notebooks.context_processors.user_theme',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASE_URL = config('DATABASE_URL', default='')
if DATABASE_URL:
    import dj_database_url

    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Explicit (not umask-dependent) permissions for uploaded files/dirs, so
# media/ stays writable by both the deploy user and whichever user the web
# server runs as, regardless of which one creates a given file or
# subdirectory first - relying on the OS default umask left newly created
# subdirectories at 755 (owner-write only), which broke the other user's
# access to anything the first one created.
FILE_UPLOAD_PERMISSIONS = 0o664
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o775

# Optional S3 for user uploads (set AWS_STORAGE_BUCKET_NAME to enable)
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='')
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='us-east-1')

if AWS_STORAGE_BUCKET_NAME:
    if 'storages' not in INSTALLED_APPS:
        INSTALLED_APPS = [*INSTALLED_APPS, 'storages']
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    MEDIA_URL = config(
        'MEDIA_URL',
        default=f'https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/',
    )

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/users/login/'
LOGIN_REDIRECT_URL = '/notebooks/'
LOGOUT_REDIRECT_URL = '/users/login/'

# Password reset emails. Console backend prints them to the runserver log
# instead of sending real mail - fine for a hackathon demo, swap for a real
# backend (SMTP/SES/etc.) before this ever goes to production.
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@cornote.local')

SESSION_COOKIE_AGE = 86400 * 30  # 30 days

MAX_PDF_SIZE_MB = config('MAX_PDF_SIZE_MB', default=50, cast=int)
MAX_UPLOAD_MB = config('MAX_UPLOAD_MB', default=MAX_PDF_SIZE_MB, cast=int)

# Claude/Anthropic AI provider
AI_PROVIDER = 'anthropic'
AI_REQUEST_TIMEOUT = config('AI_REQUEST_TIMEOUT', default=120, cast=float)
AI_MAX_RETRIES = config('AI_MAX_RETRIES', default=3, cast=int)

# Anthropic settings
ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY', default='')
ANTHROPIC_MODEL_ID = config('ANTHROPIC_MODEL_ID', default='claude-sonnet-5')
ANTHROPIC_BASE_URL = config('ANTHROPIC_BASE_URL', default='https://api.anthropic.com')
ANTHROPIC_WORKSPACE_ID = config('ANTHROPIC_WORKSPACE_ID', default='')
AWS_REGION = config('AWS_REGION', default='us-east-2')
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
AWS_SESSION_TOKEN = config('AWS_SESSION_TOKEN', default='')

# ── Agent workflow ───────────────────────────────────────────────────
# Feedback/study-plan/verifier/coach agents, built on a native Claude tool-use loop.
AGENTS_ENABLED = config('AGENTS_ENABLED', default=True, cast=bool)
AGENT_MODEL_ID = config('AGENT_MODEL_ID', default=ANTHROPIC_MODEL_ID)
# Safety limits so a confused agent can't loop and burn API credits.
AGENT_MAX_TOOL_CALLS = config('AGENT_MAX_TOOL_CALLS', default=10, cast=int)
AGENT_MAX_FEEDBACK_PER_GRADING = config('AGENT_MAX_FEEDBACK_PER_GRADING', default=3, cast=int)
AGENT_MAX_PLAN_DAYS = config('AGENT_MAX_PLAN_DAYS', default=14, cast=int)
# Run agents in the request thread instead of a background thread (tests/debugging).
AGENTS_RUN_INLINE = config('AGENTS_RUN_INLINE', default=False, cast=bool)
# Never let the test suite call real AI providers; agent tests opt in with mocks.
import sys as _sys
if len(_sys.argv) > 1 and _sys.argv[1] == 'test':
    AGENTS_ENABLED = False

# Messages framework
from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG: 'secondary',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

# Django's default logging config only sends errors to the console when
# DEBUG=True (and otherwise emails ADMINS, which does nothing if ADMINS is
# empty) - with DEBUG=False and no ADMINS configured, unhandled exceptions
# would otherwise be logged nowhere at all. Force request-level errors to
# always reach stderr (which Apache/mod_wsgi captures into its error log)
# regardless of DEBUG, so turning DEBUG off doesn't also turn off visibility
# into what's breaking.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    _INSECURE_SECRET_KEYS = {
        'unsafe-secret-key-change-me',
        'your-django-secret-key-here-replace-with-a-long-random-string',
    }
    if not SECRET_KEY or SECRET_KEY in _INSECURE_SECRET_KEYS or len(SECRET_KEY) < 20:
        raise ImproperlyConfigured(
            'SECRET_KEY must be set to a secure random value when DEBUG=False.'
        )
