from django.urls import path
from django.views.generic import RedirectView
from . import views
from .invitation import inauguration, invitation_script
app_name = 'core'
urlpatterns = [path('',views.HomeView.as_view(),name='home'),path('eventos/',views.events,name='events'),
    path('inauguracion', inauguration, name='inauguration'),
    path('inauguracion/contador.js', invitation_script, name='invitation-script'),
    path('inauguracion/', inauguration),
    path('ignaguracion', RedirectView.as_view(pattern_name='core:inauguration', permanent=True)),
    path('ignaguracion/', RedirectView.as_view(pattern_name='core:inauguration', permanent=True)),
    path('ignaguracion/contador.js', RedirectView.as_view(pattern_name='core:invitation-script', permanent=True)),
    path('reservas/',views.reservations,name='reservations'),path('reservas/mesas/',views.table_map,name='table-map'),
    path('reservas/datos/',views.reservation_guest,name='reservation-guest'),
    path('sitemap.xml',views.sitemap,name='sitemap'),path('robots.txt',views.robots,name='robots')]
