from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import Http404
from django.views.generic import TemplateView

from apps.venues.models import Area

from .services import get_area_table_map


class TableConfigurationView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = "tables/configuration.html"
    login_url = "admin:login"
    permission_required = ("venues.view_area", "venues.view_zone", "tables.view_venuetable")

    def dispatch(self, request, *args, **kwargs):
        if not settings.DEBUG:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        maps = []
        for area in Area.objects.prefetch_related("zones", "tables"):
            area_map = get_area_table_map(area)
            zone_names = {zone["id"]: zone["name"] for zone in area_map["zones"]}
            for table in area_map["tables"]:
                table["zone_name"] = zone_names.get(table["zone_id"], "Sin zona")
            maps.append(area_map)
        context["area_maps"] = maps
        return context
