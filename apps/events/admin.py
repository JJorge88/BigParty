from django.contrib import admin
from . import models

class EventReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('events.view_events') and request.user.has_perm('events.view_event_purchases')

    def get_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields if f.name not in ('proof_image', 'secure_token', 'qr_token')]

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

for model in (models.Event, models.EventSettings, models.EventTicketType, models.EventTableConfiguration,
    models.EventPurchase, models.EventPurchaseItem, models.EventPurchasePayment, models.EventTableReservation,
    models.EventTicket, models.EventScheduleHistory, models.GuardLoginAttempt):
    admin.site.register(model, EventReadOnlyAdmin)
