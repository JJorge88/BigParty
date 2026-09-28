from django.urls import path

from .views import InventoryDevelopmentView

app_name = "inventory"
urlpatterns = [path("", InventoryDevelopmentView.as_view(), name="development")]
