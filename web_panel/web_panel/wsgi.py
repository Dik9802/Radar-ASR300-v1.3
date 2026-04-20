"""WSGI config for web_panel."""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web_panel.settings")
application = get_wsgi_application()
