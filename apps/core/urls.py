from django.urls import path
from . import views
app_name = 'core'
urlpatterns = [path('',views.HomeView.as_view(),name='home'),path('eventos/',views.events,name='events'),
    path('reservas/',views.reservations,name='reservations'),path('reservas/mesas/',views.table_map,name='table-map'),
    path('reservas/datos/',views.reservation_guest,name='reservation-guest'),
    path('sitemap.xml',views.sitemap,name='sitemap'),path('robots.txt',views.robots,name='robots')]
