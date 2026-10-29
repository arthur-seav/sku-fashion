"""
Django settings for the SKU-Fashion project.

All secrets and environment-specific values are read from `.env`
(see `.env.example`). Nothing sensitive is hard-coded here.
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# DJANGO_PRODUCTION=1 on the server (set by compose.yaml): HTTPS behind Caddy,
# compressed and hashed static files. Development leaves it off.
PRODUCTION = env_bool("DJANGO_PRODUCTION", False)

# --------------------------------------------------------------------------
# Applications — one Django app per functional area (NFR-07)
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Project apps
    "core",
    "accounts",
    "catalog",
    "inventory",
    "cart",
    "promotions",
    "shipping",
    "orders",
    "payments",
    "reporting",
    "reviews",
]

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.LockoutAwareBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3  # set-password links stay valid for 3 days

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves /static/ from the app (no separate web server needed)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.store",
                "cart.context_processors.cart",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Database — PostgreSQL 17 in Docker (NFR-08)
# --------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Passwords — PBKDF2 (NFR-02)
# --------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

if "test" in sys.argv:
    # Hashing speed only matters for the test run; production stays on PBKDF2.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Internationalization
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Phnom_Penh"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static & media files
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"  # on the server, Caddy serves this folder directly at /media/

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": ("whitenoise.storage.CompressedManifestStaticFilesStorage" if PRODUCTION
                                else "django.contrib.staticfiles.storage.StaticFilesStorage")},
}

# Uploaded images are limited to 5 MB (NFR-03)
MAX_UPLOAD_IMAGE_BYTES = 5 * 1024 * 1024

# --------------------------------------------------------------------------
# Email — printed to the console in development
# --------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "SKU-Fashion <no-reply@sku-fashion.local>"

# --------------------------------------------------------------------------
# Store settings (single currency, single tax rate)
# --------------------------------------------------------------------------
STORE_NAME = "SKU-Fashion"
STORE_CURRENCY = os.getenv("STORE_CURRENCY", "USD")
STORE_TAX_RATE = Decimal(os.getenv("STORE_TAX_RATE", "0.10"))  # VAT on the discounted subtotal

# Bank-transfer details shown to customers (demo values; set real ones in .env)
STORE_BANK_NAME = os.getenv("STORE_BANK_NAME", "ABA Bank")
STORE_BANK_ACCOUNT_NAME = os.getenv("STORE_BANK_ACCOUNT_NAME", "SKU-Fashion Co., Ltd.")
STORE_BANK_ACCOUNT_NO = os.getenv("STORE_BANK_ACCOUNT_NO", "000 123 456")

# Unpaid bank-transfer orders are cancelled after this many hours (FR-X09)
UNPAID_ORDER_TIMEOUT_HOURS = int(os.getenv("UNPAID_ORDER_TIMEOUT_HOURS", "24"))

# --------------------------------------------------------------------------
# Production (HTTPS terminated by Caddy in front of gunicorn)
# --------------------------------------------------------------------------
if PRODUCTION:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # Caddy sets this header
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "3600"))
    # The site lives on a subdomain of a shared domain we do not own (sslip.io),
    # so HSTS must not cover sibling subdomains or be submitted for preloading.
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"handlers": ["console"], "level": "INFO"},
        "loggers": {"django": {"handlers": ["console"], "level": "INFO", "propagate": False}},
    }
