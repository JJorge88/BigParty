import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TransactionTestCase, override_settings

from apps.catalog.models import Category, Product
from apps.orders import services as orders
from apps.payments.models import Payment
from . import test_concurrency as access_tests


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class TabletPaymentConcurrencyTests(TransactionTestCase):
    concurrent = access_tests.OperationalConcurrencyTests.concurrent

    def setUp(self):
        access_tests.OperationalConcurrencyTests.setUp(self)
        admin = get_user_model().objects.get(username="admin")
        category = Category.objects.create(name="Bebidas", slug="bebidas")
        product = Product.objects.create(name="Gallo", slug="gallo", category=category, base_price=25)
        self.order = orders.open_table_order(self.table, admin)
        self.line = orders.add_product_to_order(self.order, product, 4, admin)
        orders.send_order(self.order, admin)
        for client, user in zip(self.clients, self.users):
            user.user_permissions.add(Permission.objects.get(codename="record_payment", content_type__app_label="payments"))
            self.assertEqual(client.post('/operacion/acceso/', {"user_id":user.pk,"pin":"2580"}, HTTP_ACCEPT="application/json").status_code, 200)
        self.url = f'/operacion/orden/{self.order.pk}/cuenta/'

    def race(self, quote_data):
        tokens = []
        for client in self.clients:
            response = client.post(self.url + 'preparar/', quote_data, HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 200)
            tokens.append(response.json()["quote"]["token"])
        results = self.concurrent([lambda client=client, token=token: client.post(self.url+'tarjeta/', {"token":token}, HTTP_ACCEPT="application/json") for client, token in zip(self.clients,tokens)])
        self.assertCountEqual([response.status_code for response in results], [200,409])
        self.assertEqual(Payment.objects.count(), 1)
        loser = next(response for response in results if response.status_code == 409)
        self.assertIn("otro usuario", loser.json()["message"])
        self.assertNotIn("IntegrityError", str(loser.content))

    def test_same_units_from_two_tablets_are_charged_once(self):
        self.race({"mode":"selection", "selection":json.dumps([{"line_id":self.line.pk,"quantity":2}])})
        self.assertEqual(Payment.objects.get().amount, 50)

    def test_stale_amount_payment_is_not_duplicated(self):
        self.race({"mode":"amount", "amount":"60"})
        self.assertEqual(Payment.objects.get().amount, 60)
