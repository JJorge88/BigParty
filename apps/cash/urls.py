from django.urls import path
from .views import CashDevelopmentView, BusinessDayDevelopmentView

app_name = "cash"
urlpatterns = [path("caja/", CashDevelopmentView.as_view(), name="development"),
               path("jornada/", BusinessDayDevelopmentView.as_view(), name="business-day")]
