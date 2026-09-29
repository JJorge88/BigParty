from django.urls import path
from . import views
app_name = 'management'
urlpatterns = [
    path('',views.home,name='home'),
    path('acceso/',views.login,name='login'),
    path('salir/',views.logout,name='logout'),
    path('actividad/',views.activity,name='activity'),
    path('cierres/',views.closures,name='closures'),
    path('jornada/abrir/',views.open_day,name='open-day'),
    path('jornada/<int:day_id>/',views.day_result,name='day-result'),
    path('jornada/<int:day_id>/cerrar/',views.close_day,name='close-day'),
    path('jornada/<int:day_id>/reabrir/',views.reopen_day,name='reopen-day'),
    path('jornada/<int:day_id>/caja/<int:session_id>/',views.cash_detail,name='cash-detail'),
    path('pagos-pendientes/',views.pending_payments,name='pending-payments'),
    path('jornada/<int:day_id>/pago/<int:payment_id>/',views.payment,name='payment'),
    path('impresiones/',views.print_jobs,name='print-jobs'),
    path('impresiones/<int:pk>/<str:action>/',views.print_action,name='print-action'),
]
