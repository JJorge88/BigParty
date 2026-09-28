from django.urls import path

from .views import TableConfigurationView

app_name = "tables"
urlpatterns = [path("", TableConfigurationView.as_view(), name="configuration")]
