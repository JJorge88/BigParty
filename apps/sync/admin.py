"""Admin source capture is explicit; operational models retain their read-only admins."""
from django.core.exceptions import PermissionDenied
from .services import enabled,own_authority,sync_atomic,track,capture_objects,record_delete
from .registry import REGISTRY

class SyncAdminMixin:
    def sync_writable(self):
        spec=REGISTRY.get(self.model._meta.label_lower)
        return not enabled() or not spec or spec.authority==own_authority()
    def has_add_permission(self,request):return self.sync_writable() and super().has_add_permission(request)
    def has_change_permission(self,request,obj=None):return self.sync_writable() and super().has_change_permission(request,obj)
    def has_delete_permission(self,request,obj=None):return not enabled() and super().has_delete_permission(request,obj)
    def save_model(self,request,obj,form,change):
        if not self.sync_writable():raise PermissionDenied('Administrado por el entorno de origen.')
        @sync_atomic('local')
        def save():
            super(SyncAdminMixin,self).save_model(request,obj,form,change)
            track(obj)
        save()
    def save_related(self,request,form,formsets,change):
        @sync_atomic('local')
        def save():
            super(SyncAdminMixin,self).save_related(request,form,formsets,change)
            track(form.instance)
            for formset in formsets:
                for obj in formset.new_objects:track(obj)
                for obj,_ in formset.changed_objects:track(obj)
        save()
