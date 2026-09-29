from django.urls import path
from .views import client_detail
app_name = 'reservation-client'
urlpatterns = [path('r/<str:secure_token>/', client_detail, name='detail')]
