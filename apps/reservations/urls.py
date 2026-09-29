from django.urls import path
from . import views
app_name = 'reservations'
urlpatterns = [path('', views.index, name='list'), path('nueva/', views.create, name='create'),
    path('configuracion/', views.configure, name='configure'), path('<str:code>/', views.detail, name='detail'),
    path('<str:code>/comprobante/', views.proof, name='proof')]
