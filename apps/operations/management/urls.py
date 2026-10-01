from django.urls import path
from . import views, catalog_views as catalog, user_views as users, table_views as tables
app_name = 'management'
urlpatterns = [
    path('mesas/', tables.listing, name='tables'),
    path('mesas/area/<int:area_id>/crear/', tables.edit, name='table-create'),
    path('mesas/<int:pk>/editar/', tables.edit, name='table-edit'),
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

urlpatterns += [
    path('inventario/', catalog.inventory, name='inventory'),
    path('inventario/producto/crear/', catalog.product_edit, name='product-create'),
    path('inventario/producto/<int:pk>/', catalog.product, name='product'),
    path('inventario/producto/<int:pk>/editar/', catalog.product_edit, name='product-edit'),
    path('inventario/producto/<int:pk>/entrada/', catalog.stock, {'action': 'receive'}, name='stock-receive'),
    path('inventario/producto/<int:pk>/ajuste/', catalog.stock, {'action': 'adjust'}, name='stock-adjust'),
    path('inventario/producto/<int:pk>/precio/', catalog.price, name='product-price'),
    path('inventario/movimientos/', catalog.movements, name='inventory-movements'),
    path('inventario/categorias/', catalog.categories, name='categories'),
    path('inventario/categorias/crear/', catalog.catalog_edit, {'kind': 'category'}, name='category-create'),
    path('inventario/categorias/<int:pk>/editar/', catalog.catalog_edit, {'kind': 'category'}, name='category-edit'),
    path('inventario/producto/<int:product_id>/grupo/crear/', catalog.catalog_edit, {'kind': 'group'}, name='group-create'),
    path('inventario/producto/<int:product_id>/grupo/<int:pk>/', catalog.catalog_edit, {'kind': 'group'}, name='group-edit'),
    path('inventario/producto/<int:product_id>/grupo/<int:group_id>/opcion/crear/', catalog.catalog_edit, {'kind': 'option'}, name='option-create'),
    path('inventario/producto/<int:product_id>/grupo/<int:group_id>/opcion/<int:pk>/', catalog.catalog_edit, {'kind': 'option'}, name='option-edit'),
    path('inventario/producto/<int:product_id>/componente/crear/', catalog.catalog_edit, {'kind': 'component'}, name='component-create'),
    path('inventario/producto/<int:product_id>/componente/<int:pk>/', catalog.catalog_edit, {'kind': 'component'}, name='component-edit'),
    path('inventario/producto/<int:product_id>/componente/<int:pk>/retirar/', catalog.component_remove, name='component-remove'),
    path('usuarios/', users.users, name='users'),
    path('usuarios/crear/', users.user_edit, name='user-create'),
    path('usuarios/<int:pk>/', users.user, name='user'),
    path('usuarios/<int:pk>/editar/', users.user_edit, name='user-edit'),
    path('usuarios/<int:pk>/pin/', users.credential, {'kind': 'pin'}, name='user-pin'),
    path('usuarios/<int:pk>/password/', users.credential, {'kind': 'password'}, name='user-password'),
    path('usuarios/<int:pk>/estado/', users.user_state, name='user-state'),
    path('usuarios/<int:pk>/permisos/', users.user_permissions, name='user-permissions'),
]

from . import configuration_views as configuration, report_views as reports, audit_views as audit
urlpatterns += [
    path('reportes/', reports.hub, name='reports'),
    path('reportes/<slug:kind>/', reports.report, name='report'),
    path('reportes/<slug:kind>/pdf/', reports.report, {'pdf': True}, name='report-pdf'),
    path('auditoria/', audit.listing, name='audit'),
    path('auditoria/<int:pk>/', audit.detail, name='audit-detail'),
    path('configuracion/', configuration.hub, name='configuration'),
    path('configuracion/negocio/', configuration.business_hub, name='configuration-business'),
    path('configuracion/<slug:kind>/', configuration.edit, name='configuration-edit'),
]
