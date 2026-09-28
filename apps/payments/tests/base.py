from apps.orders.tests.base import OrdersTestCase
from apps.orders import services as orders


class PaymentsTestCase(OrdersTestCase):
    def cash_session(self):
        from apps.cash.models import CashRegister
        from apps.cash.services import open_cash_session
        register = CashRegister.objects.create(name="Caja prueba", code="TEST", area=self.area)
        return open_cash_session(register, self.user, 0, self.user)

    def consumption(self, quantity=6, *, split=False, product=None):
        order = self.open(split=split)
        account = orders.create_subaccount(order, "Jorge", self.user) if split else None
        line = orders.add_product_to_order(order, product or self.product, quantity, self.user, subaccount=account)
        orders.send_order(order, self.user)
        return order, account, line
