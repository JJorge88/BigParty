from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Administración de BIG PARTY"
admin.site.site_title = "BIG PARTY"
admin.site.index_title = "Administración"

urlpatterns = [
    path("", include("apps.core.urls")),
    path("admin/", admin.site.urls),
    path("", include("apps.operations.urls")),
    path("impresoras/", include("apps.printing.urls")),
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
