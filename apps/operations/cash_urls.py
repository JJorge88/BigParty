from django.urls import path
from . import cash_views as views
from . import cash_sale_views as sales

from apps.printing import views as printing

app_name = "cash_operations"
urlpatterns = [
    path("", views.index, name="index"),
    path("configurar/", views.configure, name="configure"),
    path("acceso/", views.access, name="access"),
    path("bloquear/", views.lock, name="lock"),
    path("actividad/", views.activity, name="activity"),
    path("impresiones/", printing.cash_jobs, name="print-jobs"),
    path("impresiones/<int:pk>/<str:action>/", printing.cash_job_action, name="print-job-action"),
    path("orden/<int:order_id>/recibo/", printing.cash_receipt, name="receipt"),
    path("venta-rapida/", sales.quick_sales, name="quick-sales"),
    path("venta-rapida/nueva/", sales.new_sale, name="new-sale"),
    path("mesas/", sales.tables, name="tables"),
    path("orden/<int:order_id>/pedido/", sales.catalog, name="sale-order"),
    path("orden/<int:order_id>/pedido/<str:action>/", sales.catalog_action, name="sale-order-action"),
    path("orden/<int:order_id>/cuenta/", sales.checkout, name="sale-account"),
    path("orden/<int:order_id>/cuenta/<str:action>/", sales.checkout_action, name="sale-account-action"),
    path("orden/<int:order_id>/anular/", sales.cancel_sale, name="cancel-sale"),
    path("orden/<int:order_id>/completada/", sales.complete, name="sale-complete"),
    path("<str:screen>/", views.page, name="page"),
    path("accion/<str:action>/", views.action, name="action"),
]
