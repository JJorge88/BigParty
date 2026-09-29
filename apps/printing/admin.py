from django.contrib import admin
from apps.orders.admin import OperationalReadOnlyAdmin
from .models import Printer, PrintJob


@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    list_display = ('name','code','printer_type','area','host','port','paper_width','is_active')
    list_filter = ('printer_type','is_active','area')
    readonly_fields = ('created_at','updated_at')

    def has_module_permission(self, request):
        return request.user.has_perm('printing.manage_printers')

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    has_add_permission = lambda self, request: self.has_module_permission(request)
    has_change_permission = has_view_permission
    has_delete_permission = lambda self, request, obj=None: False


@admin.register(PrintJob)
class PrintJobAdmin(OperationalReadOnlyAdmin):
    list_display = ('created_at','printer','job_type','status','attempt_count','order','preparation_ticket','reprint_of')
    list_filter = ('printer','status','job_type','created_at')
    list_select_related = ('printer','order','preparation_ticket')
