from django.urls import path
from .views import PaymentsDevelopmentView

app_name = "payments"
urlpatterns = [path("", PaymentsDevelopmentView.as_view(), name="development")]
