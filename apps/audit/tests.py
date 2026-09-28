from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import is_aware

from .models import AuditLog

User = get_user_model()


class AuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="actor")
        cls.log = AuditLog.objects.create(
            user=cls.user,
            action="prueba",
            entity="usuario",
            entity_id=str(cls.user.pk),
            data={"motivo": "Comprobación de infraestructura"},
        )

    def test_log_creation_with_json_and_aware_timestamp(self):
        self.log.refresh_from_db()
        self.assertEqual(self.log.data["motivo"], "Comprobación de infraestructura")
        self.assertEqual(self.log.user, self.user)
        self.assertTrue(is_aware(self.log.created_at))

    def test_log_survives_user_deletion(self):
        self.user.delete()
        self.log.refresh_from_db()
        self.assertIsNone(self.log.user)

    def test_system_event_without_user(self):
        log = AuditLog.objects.create(action="prueba", entity="sistema")
        self.assertIsNone(log.user)
        self.assertEqual(log.data, {})

    def test_admin_audit_is_read_only_even_for_superuser(self):
        admin = User.objects.create_superuser(username="admin", password="Test-password-72!")
        self.client.force_login(admin)
        change_url = reverse("admin:audit_auditlog_change", args=[self.log.pk])
        self.assertEqual(self.client.get(change_url).status_code, 200)
        self.assertEqual(self.client.post(change_url, {"action": "alterado"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:audit_auditlog_add")).status_code, 403)
        delete_url = reverse("admin:audit_auditlog_delete", args=[self.log.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.client.post(reverse("admin:audit_auditlog_changelist"), {
            "action": "delete_selected", "_selected_action": [self.log.pk], "post": "yes",
        })
        self.log.refresh_from_db()
        self.assertEqual(self.log.action, "prueba")
