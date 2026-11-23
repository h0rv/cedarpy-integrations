"""Set DJANGO_SETTINGS_MODULE=examples.frameworks.django_reports in a dedicated
WSGI process behind authentication that sets REMOTE_USER and cedar_web.session_id.
"""

from collections.abc import Callable

import cedarpy_web
import cedarpy_wsgi
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.wsgi import get_wsgi_application
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.http import require_safe

from .report_access import export_facts, export_permission

ROOT_URLCONF = __name__


@require_safe
def export(request):
    return HttpResponse("report,total\nsales,42\n", content_type="text/csv")


urlpatterns = [path("export", export)]


def create_app(
    *,
    can_export: Callable[[str], bool],
    is_stepped_up: Callable[[cedarpy_web.Session], bool],
    challenge: str = "Bearer",
):
    if settings.ROOT_URLCONF != __name__:
        raise ImproperlyConfigured("Use the export-only URLconf for this WSGI app")
    return cedarpy_wsgi.require_authorization(
        get_wsgi_application(),
        export_permission,
        load_facts=export_facts(can_export, is_stepped_up),
        challenge=challenge,
    )
