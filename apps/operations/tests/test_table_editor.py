from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.tables.models import VenueTable
from apps.tables.services import get_area_table_map
from apps.venues.models import Area, Zone


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class TableEditorTests(TestCase):
    def setUp(self):
        self.area = Area.objects.create(name='Sala', slug='sala')
        self.other = Area.objects.create(name='Otra', slug='otra')
        self.user = User.objects.create_user(username='editor', role='GERENTE', password='Editor-test-71!')
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='tables', codename__in=['view_venuetable','add_venuetable','change_venuetable']))
        self.client.post('/gerencia/acceso/', {'username':'editor','password':'Editor-test-71!'})
        self.url=f'/gerencia/mesas/area/{self.area.pk}/crear/'
        self.data={'name':'Mesa nueva','capacity':4,'layout_shape':'RECTANGLE','layout_x':'10', 'layout_y':'20',
            'layout_width':'15','layout_height':'15','is_active':'on','operational_status':'ACTIVE','reservable_web':'on'}

    def test_create_update_and_operation_map(self):
        self.assertEqual(self.client.post(self.url,self.data).status_code,302)
        table=VenueTable.objects.get(name='Mesa nueva')
        self.assertEqual(get_area_table_map(self.area)['tables'][0]['layout']['x'],10)
        edit=f'/gerencia/mesas/{table.pk}/editar/'
        self.assertContains(self.client.get(edit),'Guardar mesa')
        data={**self.data,'revision':table.updated_at.isoformat(),'layout_x':'40'}
        self.assertEqual(self.client.post(edit,data).status_code,302)
        table.refresh_from_db()
        self.assertEqual(table.layout_x,40)
        self.assertEqual(AuditLog.objects.filter(entity_id=str(table.pk),action__in=['table.created','table.configuration_updated']).count(),2)
        self.assertEqual(self.client.post(edit,data).status_code,400)
        table.refresh_from_db(); self.assertEqual(table.layout_x,40)

    def test_invalid_position_duplicate_and_foreign_zone(self):
        self.assertEqual(self.client.post(self.url,{**self.data,'layout_x':'99'}).status_code,400)
        zone=Zone.objects.create(area=self.other,name='Otro',slug='otro')
        self.assertEqual(self.client.post(self.url,{**self.data,'zone':zone.pk}).status_code,400)
        self.assertFalse(VenueTable.objects.exists())
        self.client.post(self.url,self.data)
        self.assertEqual(self.client.post(self.url,self.data).status_code,400)
        self.assertEqual(VenueTable.objects.count(),1)

    def test_read_permission_does_not_grant_write(self):
        self.user.user_permissions.remove(*Permission.objects.filter(codename__in=['add_venuetable','change_venuetable']))
        self.assertContains(self.client.get('/gerencia/mesas/'),'Sala')
        self.assertNotContains(self.client.get('/gerencia/mesas/'),'Crear mesa')
        self.assertEqual(self.client.post(self.url,self.data).status_code,403)
        self.assertFalse(VenueTable.objects.exists())

    def test_login_and_csrf_required(self):
        self.assertEqual(Client().get('/gerencia/mesas/').status_code,302)
        client=Client(enforce_csrf_checks=True)
        client.cookies=self.client.cookies
        self.assertEqual(client.post(self.url,self.data).status_code,403)

    @override_settings(SYNC_ENABLED=True,DEPLOYMENT_MODE='cloud')
    def test_cloud_cannot_write_local_map(self):
        self.assertEqual(self.client.post(self.url,self.data).status_code,403)
        self.assertFalse(VenueTable.objects.exists())
