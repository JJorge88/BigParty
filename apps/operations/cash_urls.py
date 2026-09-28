from django.urls import path
from . import cash_views as views

app_name = "cash_operations"
urlpatterns = [
    path("", views.index, name="index"),
    path("configurar/", views.configure, name="configure"),
    path("acceso/", views.access, name="access"),
    path("bloquear/", views.lock, name="lock"),
    path("actividad/", views.activity, name="activity"),
    path("<str:screen>/", views.page, name="page"),
    path("accion/<str:action>/", views.action, name="action"),
]
