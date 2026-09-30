from django.urls import path
from . import api
app_name='sync'
urlpatterns=[path('push/',api.push,name='push'),path('pull/',api.pull,name='pull'),path('ack/',api.ack,name='ack'),path('status/',api.status,name='status')]
