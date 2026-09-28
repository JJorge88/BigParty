from django.urls import path

from .views import CatalogDevelopmentView

app_name = "catalog"
urlpatterns = [path("", CatalogDevelopmentView.as_view(), name="development")]
