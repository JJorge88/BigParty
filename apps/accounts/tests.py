from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AdminUserChangeForm

User = get_user_model()


class UserTests(TestCase):
    def test_custom_user_creation(self):
        user = User.objects.create_user(username="mesero", password="Test-password-72!")
        self.assertEqual(user._meta.label, "accounts.User")
        self.assertTrue(user.check_password("Test-password-72!"))
        self.assertEqual(user.role, User.Role.MESERO)
        self.assertFalse(user.is_staff)

    def test_every_role_can_be_persisted(self):
        self.assertEqual(set(User.Role.values), {"MESERO", "CAJERO", "GERENTE", "PROPIETARIO", "GUARDIA"})
        for role in User.Role.values:
            with self.subTest(role=role):
                user = User.objects.create_user(username=role.lower(), role=role)
                user.refresh_from_db()
                self.assertEqual(user.role, role)

    def test_database_rejects_unknown_role(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="invalid", role="DESCONOCIDO")

    def test_individual_permissions_are_independent_of_role(self):
        user = User.objects.create_user(username="propietario", role=User.Role.PROPIETARIO)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_perm("audit.view_auditlog"))
        permission = Permission.objects.get(content_type__app_label="audit", codename="view_auditlog")
        user.user_permissions.add(permission)
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_perm("audit.view_auditlog"))
        self.assertFalse(user.has_perm("audit.delete_auditlog"))

    def test_pin_is_hashed_and_persisted(self):
        user = User.objects.create_user(username="pin")
        user.set_pin("012345")
        user.save(update_fields=["pin_hash"])
        user.refresh_from_db()
        self.assertNotEqual(user.pin_hash, "012345")
        self.assertIsNotNone(identify_hasher(user.pin_hash))
        self.assertTrue(user.check_pin("012345"))
        self.assertFalse(user.check_pin("654321"))
        self.assertFalse(user.check_password("012345"))

    def test_same_pin_has_different_salts(self):
        first, second = User(), User()
        first.set_pin("123456")
        second.set_pin("123456")
        self.assertNotEqual(first.pin_hash, second.pin_hash)

    def test_optional_and_disabled_pin(self):
        user = User()
        self.assertFalse(user.check_pin("1234"))
        self.assertFalse(user.check_pin(None))
        user.set_pin("1234")
        user.set_pin(None)
        self.assertFalse(user.check_pin("1234"))

    def test_pin_validation(self):
        for invalid in ("", "123", "1" * 13, "abcd", 1234, "１２３４", " 1234"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                User().set_pin(invalid)


class UserAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(username="admin", password="Test-password-72!")
        cls.user = User.objects.create_user(username="usuario", role=User.Role.CAJERO)
        cls.user.set_pin("123456")
        cls.user.save(update_fields=["pin_hash"])

    def setUp(self):
        self.client.force_login(self.admin_user)

    def change_data(self, **extra):
        return {
            "username": self.user.username,
            "role": self.user.role,
            "is_active": "on",
            "date_joined": self.user.date_joined.isoformat(),
            "date_joined_0": timezone.localtime(self.user.date_joined).strftime("%Y-%m-%d"),
            "date_joined_1": timezone.localtime(self.user.date_joined).strftime("%H:%M:%S"),
            **extra,
        }

    def test_admin_user_pages_render_without_pin_hash(self):
        urls = [
            reverse("admin:accounts_user_changelist"),
            reverse("admin:accounts_user_add"),
            reverse("admin:accounts_user_change", args=[self.user.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.user.pin_hash)
                self.assertNotContains(response, 'name="pin_hash"')

    def test_admin_changes_pin_with_confirmation(self):
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[self.user.pk]),
            self.change_data(new_pin="098765", confirm_pin="098765"),
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_pin("098765"))
        self.assertFalse(self.user.check_pin("123456"))

    def test_empty_admin_pin_preserves_hash(self):
        original_hash = self.user.pin_hash
        form = AdminUserChangeForm(data=self.change_data(), instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.pin_hash, original_hash)

    def test_mismatching_admin_pin_is_rejected(self):
        form = AdminUserChangeForm(
            data=self.change_data(new_pin="123456", confirm_pin="654321"), instance=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("confirm_pin", form.errors)

    def test_admin_creates_custom_user(self):
        response = self.client.post(reverse("admin:accounts_user_add"), {
            "username": "nuevo",
            "role": User.Role.GUARDIA,
            "password1": "A-distinct-test-password-81!",
            "password2": "A-distinct-test-password-81!",
            "usable_password": "true",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="nuevo")
        self.assertEqual(user.role, User.Role.GUARDIA)
        self.assertTrue(user.check_password("A-distinct-test-password-81!"))
