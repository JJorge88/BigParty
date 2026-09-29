from django.contrib import admin
from .models import Reservation, ReservationPayment, ReservationSettings

class ReadOnlyReservationAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('reservations.view_reservations')
    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

@admin.register(Reservation)
class ReservationAdmin(ReadOnlyReservationAdmin):
    list_display = ['public_code', 'customer_name', 'table', 'reservation_date', 'start_time', 'status']
    list_filter = ['status', 'reservation_date']
    search_fields = ['public_code', 'customer_name', 'customer_phone']
    exclude = ['secure_token']
    def get_readonly_fields(self, request, obj=None):
        return [f for f in super().get_readonly_fields(request, obj) if f != 'secure_token']

@admin.register(ReservationPayment)
class ReservationPaymentAdmin(ReadOnlyReservationAdmin):
    list_display = ['reservation', 'amount', 'status', 'submitted_at']
    exclude = ['proof_image']
    def get_readonly_fields(self, request, obj=None):
        return [f for f in super().get_readonly_fields(request, obj) if f != 'proof_image']

@admin.register(ReservationSettings)
class ReservationSettingsAdmin(ReadOnlyReservationAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('reservations.configure_reservations')
