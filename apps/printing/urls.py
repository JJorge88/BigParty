from django.urls import path
from . import views
app_name = 'printing'
urlpatterns = [
    path('',views.printers,name='printers'),
    path('puente/nuevo/',views.create_bridge,name='bridge-create'),
    path('puente/descargar/',views.bridge_download,name='bridge-download'),
    path('puente/api/trabajo/',views.bridge_next,name='bridge-next'),
    path('puente/api/trabajo/<int:pk>/completar/',views.bridge_complete,name='bridge-complete'),
    path('nueva/',views.configure,name='create'),
    path('<int:pk>/',views.configure,name='configure'),
    path('<int:pk>/prueba/',views.test,name='test'),
    path('trabajos/',views.jobs,name='jobs'),
    path('trabajos/<int:pk>/<str:action>/',views.job_action,name='job-action'),
]
