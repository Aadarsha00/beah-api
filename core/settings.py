import json
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load BASE_DIR/.env when it exists. override=False means a real process
# environment variable always wins, so cPanel or systemd configuration is never
# silently replaced by a stale checked-out file.
load_dotenv(BASE_DIR / ".env", override=False)


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(
        f"{name} must be one of true/false, 1/0, yes/no, or on/off."
    )


def env_list(name, default=""):
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


def env_int(name, default):
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc


def env_float(name, default):
    value = os.getenv(name, str(default))
    try:
        return float(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a number.") from exc


def env_json(name, default=None):
    value = os.getenv(name)
    if not value:
        return {} if default is None else default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ImproperlyConfigured(f"{name} must contain valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ImproperlyConfigured(f"{name} must contain a JSON object.")
    return parsed


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} is required.")
    return value


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-local-development-only"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# Every production guard below is skipped while DEBUG is true, so a .env copied
# from a developer machine onto a real host would silently disable all of them
# and serve debug tracebacks publicly. A real hostname is the tell: refuse.
if DEBUG:
    _publicly_reachable_hosts = [
        host
        for host in ALLOWED_HOSTS
        if host not in {"localhost", "127.0.0.1", "::1", "testserver"}
    ]
    if _publicly_reachable_hosts:
        raise ImproperlyConfigured(
            "DJANGO_DEBUG is true but DJANGO_ALLOWED_HOSTS contains "
            f"{_publicly_reachable_hosts}. Refusing to start a debug server on "
            "a real hostname: it would expose tracebacks and settings, and it "
            "skips the HTTPS, database, and email checks below. "
            "Set DJANGO_DEBUG=false."
        )

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "djoser",
    "corsheaders",
]

LOCAL_APPS = [
    "accounts",
    "services",
    "appointments",
    "gallery",
    "blog",
    "api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not DEBUG:
    MIDDLEWARE.insert(2, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").lower()
if DB_ENGINE == "mysql":
    database_options = {
        "charset": "utf8mb4",
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }
    database_ssl_ca = os.getenv("DB_SSL_CA", "").strip()
    if database_ssl_ca:
        database_options["ssl"] = {"ca": database_ssl_ca}

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": required_env("DB_NAME"),
            "USER": required_env("DB_USER"),
            "PASSWORD": required_env("DB_PASSWORD"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "3306"),
            "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60 if not DEBUG else 0),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": database_options,
        }
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured("DB_ENGINE must be either 'sqlite' or 'mysql'.")

# DRF throttles keep their counters in the default cache. A per-process cache
# silently multiplies every rate limit by the worker count and resets on each
# restart, so production has to pick a shared backend on purpose.
CACHE_URL = os.getenv("DJANGO_CACHE_URL", "").strip()
CACHE_TABLE = os.getenv("DJANGO_CACHE_TABLE", "").strip()
ALLOW_LOCAL_MEMORY_CACHE = env_bool("DJANGO_ALLOW_LOCAL_MEMORY_CACHE", False)

if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
        }
    }
elif CACHE_TABLE:
    # Zero extra infrastructure: run `manage.py createcachetable` once.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": CACHE_TABLE,
        }
    }
else:
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True

STATIC_URL = os.getenv("DJANGO_STATIC_URL", "/static/")
STATIC_ROOT = Path(os.getenv("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))

DEFAULT_STORAGE_BACKEND = os.getenv(
    "DJANGO_DEFAULT_STORAGE_BACKEND",
    "django.core.files.storage.FileSystemStorage",
)
DEFAULT_STORAGE_OPTIONS = env_json("DJANGO_DEFAULT_STORAGE_OPTIONS")
STORAGES = {
    "default": {"BACKEND": DEFAULT_STORAGE_BACKEND},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
if DEFAULT_STORAGE_OPTIONS:
    STORAGES["default"]["OPTIONS"] = DEFAULT_STORAGE_OPTIONS

MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT_ENV = os.getenv("DJANGO_MEDIA_ROOT", "").strip()
MEDIA_ROOT = Path(MEDIA_ROOT_ENV) if MEDIA_ROOT_ENV else BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "api.pagination.StandardPageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("ANON_THROTTLE_RATE", "100/hour"),
        "user": os.getenv("USER_THROTTLE_RATE", "1000/hour"),
        "contact": os.getenv("CONTACT_THROTTLE_RATE", "5/hour"),
    },
}
if os.getenv("DJANGO_NUM_PROXIES", "").strip():
    REST_FRAMEWORK["NUM_PROXIES"] = env_int("DJANGO_NUM_PROXIES", 0)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

DJOSER = {
    "LOGIN_FIELD": "email",
    "USER_CREATE_PASSWORD_RETYPE": True,
    "SET_PASSWORD_RETYPE": True,
    "ACTIVATION_URL": "activate/{uid}/{token}",
    "SEND_ACTIVATION_EMAIL": env_bool("SEND_ACTIVATION_EMAIL", True),
    "SEND_CONFIRMATION_EMAIL": False,
    "EMAIL_FRONTEND_DOMAIN": os.getenv(
        "EMAIL_FRONTEND_DOMAIN", "beautifulbrowsandhenna.com"
    ),
    "EMAIL_FRONTEND_PROTOCOL": os.getenv("EMAIL_FRONTEND_PROTOCOL", "https"),
    "EMAIL_FRONTEND_SITE_NAME": os.getenv(
        "EMAIL_FRONTEND_SITE_NAME", "Beautiful Brows & Henna"
    ),
    "PASSWORD_RESET_CONFIRM_URL": "password/reset/confirm/{uid}/{token}",
    "SERIALIZERS": {
        "user_create": "accounts.serializers.UserCreateSerializer",
        "user_create_password_retype": "accounts.serializers.UserCreateSerializer",
        "user": "accounts.serializers.UserSerializer",
        "current_user": "accounts.serializers.UserSerializer",
    },
    "PERMISSIONS": {
        "user": ["rest_framework.permissions.IsAuthenticated"],
        "user_list": ["rest_framework.permissions.IsAdminUser"],
        "user_create": ["rest_framework.permissions.AllowAny"],
        "user_delete": ["rest_framework.permissions.IsAuthenticated"],
    },
}

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    ),
)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 15)
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "Beautiful Brows & Henna <beautifulbrowsandhenna@gmail.com>"
)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip()
SEND_CONTACT_EMAILS = env_bool("SEND_CONTACT_EMAILS", not DEBUG)
# Unhandled 500s are mailed here so a failed booking is noticed the same day
# rather than sitting unread in a server log.
ADMINS = [("Site owner", ADMIN_EMAIL)] if ADMIN_EMAIL else []

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False
)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

USE_X_FORWARDED_HOST = env_bool("DJANGO_USE_X_FORWARDED_HOST", False)
if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO", False):
    # Enable only when the application is behind a trusted proxy that strips
    # client-supplied X-Forwarded-Proto and sets its own value.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "mail_admins": {
            "class": "django.utils.log.AdminEmailHandler",
            "level": "ERROR",
            # Plain text only: the HTML report embeds local variables, which
            # for this application means customer contact details.
            "include_html": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            # WARNING keeps 4xx patterns visible in the console; the
            # mail_admins handler's own ERROR level means only 500s are mailed.
            "handlers": ["console", "mail_admins"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    try:
        import sentry_sdk
    except ImportError as exc:
        raise ImproperlyConfigured(
            "SENTRY_DSN is set but sentry-sdk is not installed. "
            "Add it to requirements.txt or clear SENTRY_DSN."
        ) from exc

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("SENTRY_RELEASE") or None,
        traces_sample_rate=env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0),
        # Customer names, emails, and phone numbers must not leave the server.
        send_default_pii=False,
    )


def _is_local_origin(value):
    hostname = urlparse(value).hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}


if not DEBUG:
    configuration_errors = []

    if (
        len(SECRET_KEY) < 50
        or SECRET_KEY.startswith("django-insecure-")
        or SECRET_KEY == "replace-with-a-long-random-secret"
    ):
        configuration_errors.append(
            "DJANGO_SECRET_KEY must be a long, random production secret."
        )

    production_hosts = [
        host
        for host in ALLOWED_HOSTS
        if host not in {"localhost", "127.0.0.1", "::1"}
        and not host.endswith(".example.com")
    ]
    if "*" in ALLOWED_HOSTS or not production_hosts:
        configuration_errors.append(
            "DJANGO_ALLOWED_HOSTS must contain the real API hostname and must not use '*'."
        )

    invalid_cors_origins = [
        origin
        for origin in CORS_ALLOWED_ORIGINS
        if urlparse(origin).scheme != "https" and not _is_local_origin(origin)
    ]
    production_cors_origins = [
        origin
        for origin in CORS_ALLOWED_ORIGINS
        if not _is_local_origin(origin)
        and not (urlparse(origin).hostname or "").endswith(".example.com")
    ]
    if invalid_cors_origins or not production_cors_origins:
        configuration_errors.append(
            "CORS_ALLOWED_ORIGINS must contain the real HTTPS frontend origin."
        )

    if DB_ENGINE == "sqlite":
        configuration_errors.append(
            "Production SQLite is disabled because booking row locks require MySQL. "
            "Set DB_ENGINE=mysql and configure DB_* values."
        )

    if (
        DEFAULT_STORAGE_BACKEND
        == "django.core.files.storage.FileSystemStorage"
        and not MEDIA_ROOT_ENV
    ):
        configuration_errors.append(
            "DJANGO_MEDIA_ROOT must explicitly point to durable persistent storage "
            "when using FileSystemStorage."
        )
    elif DEFAULT_STORAGE_BACKEND == "django.core.files.storage.FileSystemStorage":
        try:
            MEDIA_ROOT.resolve().relative_to(BASE_DIR.resolve())
        except ValueError:
            pass
        else:
            configuration_errors.append(
                "DJANGO_MEDIA_ROOT must be outside the application release directory "
                "so a code deployment cannot replace uploaded media."
            )

    unsafe_email_backends = {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }
    if DJOSER["SEND_ACTIVATION_EMAIL"] and EMAIL_BACKEND in unsafe_email_backends:
        configuration_errors.append(
            "A real email backend is required while activation email is enabled."
        )
    if (
        EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        and (
            not EMAIL_HOST
            or EMAIL_HOST in {"localhost", "mail.example.com"}
            or not DEFAULT_FROM_EMAIL
        )
    ):
        configuration_errors.append(
            "Configure the real SMTP host and DEFAULT_FROM_EMAIL."
        )
    if EMAIL_USE_TLS and EMAIL_USE_SSL:
        configuration_errors.append(
            "EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled."
        )
    if SEND_CONTACT_EMAILS and not ADMIN_EMAIL:
        configuration_errors.append(
            "ADMIN_EMAIL is required when SEND_CONTACT_EMAILS is enabled."
        )
    if not (CACHE_URL or CACHE_TABLE or ALLOW_LOCAL_MEMORY_CACHE):
        configuration_errors.append(
            "Throttle counters need a shared cache. Set DJANGO_CACHE_URL for "
            "Redis, or DJANGO_CACHE_TABLE after running createcachetable, or "
            "set DJANGO_ALLOW_LOCAL_MEMORY_CACHE=true to accept per-process "
            "limits on a single-worker deployment."
        )
    if not SECURE_SSL_REDIRECT:
        configuration_errors.append("SECURE_SSL_REDIRECT must be enabled in production.")
    if not SESSION_COOKIE_SECURE or not CSRF_COOKIE_SECURE:
        configuration_errors.append(
            "SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE must be enabled in production."
        )
    invalid_csrf_origins = [
        origin
        for origin in CSRF_TRUSTED_ORIGINS
        if urlparse(origin).scheme != "https" and not _is_local_origin(origin)
    ]
    if invalid_csrf_origins:
        configuration_errors.append(
            "CSRF_TRUSTED_ORIGINS may contain only HTTPS production origins."
        )
    if LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        configuration_errors.append(
            "DJANGO_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )

    if configuration_errors:
        details = "\n - ".join(configuration_errors)
        raise ImproperlyConfigured(f"Production configuration errors:\n - {details}")
