from django.urls import path
from . import views
app_name = 'printing'
urlpatterns = [
    path('',views.printers,name='printers'),
    path('<int:pk>/',views.configure,name='configure'),
    path('<int:pk>/prueba/',views.test,name='test'),
    path('trabajos/',views.jobs,name='jobs'),
    path('trabajos/<int:pk>/<str:action>/',views.job_action,name='job-action'),
]
