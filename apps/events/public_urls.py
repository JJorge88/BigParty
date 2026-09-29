from django.urls import path
from . import views
app_name = 'event-public'
urlpatterns = [path('compra/<str:secure_token>/', views.portal, name='portal'),
    path('compra/<str:secure_token>/pdf/', views.purchase_pdf, name='all-pdf'),
    path('compra/<str:secure_token>/pdf/<str:number>/', views.purchase_pdf, name='pdf'),
    path('<slug:slug>/', views.public_event, name='event')]
