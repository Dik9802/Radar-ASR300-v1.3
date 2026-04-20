"""Django settings for web_panel (panel de configuración del Radar ASR300P)."""
import os
import sys
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para que los emojis de display_manager.py
# no fallen con 'charmap' codec en Windows. En Linux (Orange Pi) no afecta.
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent

# Agregar el directorio Python/ al path para importar módulos del sistema
PYTHON_DIR = BASE_DIR.parent  # c:/.../Python/
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

SECRET_KEY = "radar-asr300p-local-panel-key"

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "web_panel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "web_panel.wsgi.application"

DATABASES = {}

STATIC_URL = "/static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Ruta al config.ini del sistema
CONFIG_INI_PATH = str(PYTHON_DIR / "config.ini")
