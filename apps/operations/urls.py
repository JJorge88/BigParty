from django.urls import path
from . import views

app_name = "operations"
urlpatterns = [
    path("dispositivo/configurar/", views.configure_device, name="configure-device"),
    path("operacion/", views.index, name="index"),
    path("operacion/acceso/", views.access, name="access"),
    path("operacion/bloquear/", views.lock, name="lock"),
    path("operacion/actividad/", views.activity, name="activity"),
    path("operacion/mesas/", views.tables, name="tables"),
    path("operacion/mesas/<int:table_id>/abrir/", views.open_table, name="open-table"),
]
