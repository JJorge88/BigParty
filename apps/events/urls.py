from django.urls import path
from . import views
app_name = 'events'
urlpatterns = [path('', views.index, name='list'), path('nuevo/', views.wizard, name='create'),
    path('configuracion/', views.configure, name='settings'), path('<int:pk>/paso/<int:step>/', views.wizard, name='wizard'),
    path('<int:pk>/', views.detail, name='detail'), path('<int:pk>/vista-previa/', views.preview, name='preview'),
    path('<int:pk>/compras/', views.purchases, name='purchases'), path('compra/<str:code>/', views.purchase_review, name='purchase'),
    path('compra/<str:code>/comprobante/', views.proof, name='proof'), path('cortesia/<str:number>/pdf/', views.courtesy_pdf, name='courtesy-pdf')]
