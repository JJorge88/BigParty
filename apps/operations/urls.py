from django.urls import path
from . import views
from . import order_views, account_views

from apps.printing import views as printing

app_name = "operations"
urlpatterns = [
    path("operacion/orden/<int:order_id>/recibo/", printing.waiter_receipt, name="receipt"),
    path("operacion/orden/<int:order_id>/cuenta/", account_views.account_page, name="account"),
    path("operacion/orden/<int:order_id>/cuenta/<str:action>/", account_views.account_action, name="account-action"),
    path("dispositivo/configurar/", views.configure_device, name="configure-device"),
    path("operacion/", views.index, name="index"),
    path("operacion/acceso/", views.access, name="access"),
    path("operacion/bloquear/", views.lock, name="lock"),
    path("operacion/actividad/", views.activity, name="activity"),
    path("operacion/mesas/", views.tables, name="tables"),
    path("operacion/mesas/<int:table_id>/abrir/", views.open_table, name="open-table"),
    path("operacion/orden/<int:order_id>/pedido/", order_views.order_page, name="order"),
    path("operacion/orden/<int:order_id>/pedido/<str:action>/", order_views.order_action, name="order-action"),
]
