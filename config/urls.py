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
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
