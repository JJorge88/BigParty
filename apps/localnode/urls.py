from django.urls import path
from . import views
app_name = 'localnode'
urlpatterns = [path('healthz/', views.health, name='health'), path('readyz/', views.ready, name='ready'),
               path('gerencia/configuracion/nodo-local/', views.status, name='status')]
