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

SESSION_COOKIE_AGE = 86400 * 30  # 30 days

OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
MAX_PDF_SIZE_MB = config('MAX_PDF_SIZE_MB', default=50, cast=int)
MAX_UPLOAD_MB = config('MAX_UPLOAD_MB', default=MAX_PDF_SIZE_MB, cast=int)

# AI provider — set to 'openai', 'groq', or 'gemini'
AI_PROVIDER = config('AI_PROVIDER', default='openai')
AI_REQUEST_TIMEOUT = config('AI_REQUEST_TIMEOUT', default=120, cast=float)
AI_MAX_RETRIES = config('AI_MAX_RETRIES', default=3, cast=int)
OPENAI_CHAT_MODEL = config('OPENAI_CHAT_MODEL', default='gpt-4o-mini')

# Groq settings (used when AI_PROVIDER='groq')
GROQ_API_KEY = config('GROQ_API_KEY', default='')
GROQ_MODEL_ID = config('GROQ_MODEL_ID', default='llama-3.3-70b-versatile')

# Gemini settings (used when AI_PROVIDER='gemini')
GEMINI_API_KEY = config('GEMINI_API_KEY', default='')
GEMINI_MODEL_ID = config('GEMINI_MODEL_ID', default='gemini-2.0-flash')
GEMINI_TTS_MODEL_ID = config('GEMINI_TTS_MODEL_ID', default='gemini-3.1-flash-tts-preview')

# Messages framework
from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG: 'secondary',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    if not SECRET_KEY or SECRET_KEY == 'unsafe-secret-key-change-me':
        raise ImproperlyConfigured(
            'SECRET_KEY must be set to a secure random value when DEBUG=False.'
        )
