"""WSGI config for AuditFlow AI."""

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auditflow.settings")

application = get_wsgi_application()

