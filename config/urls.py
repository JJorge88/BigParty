from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from apps.core.public_media import serve as public_media
from apps.sync import views as sync_views
from apps.core.ops.views import backup_status

admin.site.site_header = "Administración de BIG PARTY"
admin.site.site_title = "BIG PARTY"
admin.site.index_title = "Administración"

urlpatterns = [
    path("archivos-publicos/<path:path>", public_media, name="public-media"),
    path("gerencia/configuracion/backups/",backup_status,name="backup-status"),
    path("gerencia/configuracion/sincronizacion/",sync_views.status,name="sync-status"),
    path("api/sync/v1/", include("apps.sync.urls")),
    path("", include("apps.localnode.urls")),
    path("gerencia/eventos/", include("apps.events.urls")),
    path("eventos/", include("apps.events.public_urls")),
    path("", include("apps.events.access_urls")),
    path("", include("apps.core.urls")),
    path("admin/", admin.site.urls),
    path("", include("apps.operations.urls")),
    path("impresoras/", include("apps.printing.urls")),
    path("gerencia/reservas/", include("apps.reservations.urls")),
    path("reservas/", include("apps.reservations.client_urls")),
    path("gerencia/", include("apps.operations.management.urls")),
    path("caja/", include("apps.operations.cash_urls")),
]

if settings.DEBUG:
    urlpatterns += [path("dev/mesas/", include("apps.tables.urls"))]
    urlpatterns += [path("dev/catalogo/", include("apps.catalog.urls"))]
    urlpatterns += [path("dev/inventario/", include("apps.inventory.urls"))]
    urlpatterns += [path("dev/ordenes/", include("apps.orders.urls"))]
    urlpatterns += [path("dev/pagos/", include("apps.payments.urls"))]
    urlpatterns += [path("dev/", include("apps.cash.urls"))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler400 = 'apps.core.ops.error_views.bad_request'
handler403 = 'apps.core.ops.error_views.forbidden'
handler404 = 'apps.core.ops.error_views.not_found'
handler500 = 'apps.core.ops.error_views.server_error'
