import cedarpy_web
import cedarpy_wsgi


def protect_exports(export_app, permission: cedarpy_web.Permission, lookup_export_facts):
    return cedarpy_wsgi.require_authorization(
        export_app,
        permission,
        load_facts=lookup_export_facts,
        challenge='Basic realm="reports"',
    )
