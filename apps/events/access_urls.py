from django.urls import path
from . import access, views
app_name = 'event-access'
urlpatterns = [path('acceso/', access.scanner, name='scanner'), path('acceso/ingresar/', access.sign_in, name='login'),
    path('acceso/salir/', access.sign_out, name='logout'), path('acceso/escanear/', access.scan, name='scan'),
    path('entrada/<str:qr_token>/', views.ticket_page, name='ticket'), path('entrada/<str:qr_token>/qr/', views.qr_image, name='qr')]
