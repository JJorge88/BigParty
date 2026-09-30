from django.urls import path
from . import views
from .invitation import inauguration
app_name = 'core'
urlpatterns = [path('',views.HomeView.as_view(),name='home'),path('eventos/',views.events,name='events'),
    path('ignaguracion', inauguration, name='inauguration'),
    path('ignaguracion/', inauguration),
    path('reservas/',views.reservations,name='reservations'),path('reservas/mesas/',views.table_map,name='table-map'),
    path('reservas/datos/',views.reservation_guest,name='reservation-guest'),
    path('sitemap.xml',views.sitemap,name='sitemap'),path('robots.txt',views.robots,name='robots')]
