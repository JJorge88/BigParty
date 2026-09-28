from django.urls import path

from .views import OrdersDevelopmentView

app_name = "orders"
urlpatterns = [path("", OrdersDevelopmentView.as_view(), name="development")]
