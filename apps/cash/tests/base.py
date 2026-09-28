from decimal import Decimal as D

from apps.orders.tests.base import OrdersTestCase
from apps.orders import services as orders
from apps.payments import services as payments
from apps.cash.models import CashRegister
from apps.cash import services as cash


class CashTestCase(OrdersTestCase):
    def register(self, code="SPORT", area=None):
        return CashRegister.objects.create(name=f"Caja {code}", code=code, area=area or self.area)

    def session(self, opening="100.00", register=None):
        return cash.open_cash_session(register or self.register(), self.user, D(opening), self.user)

    def consumption(self, quantity=4):
        order = self.open()
        line = orders.add_product_to_order(order, self.product, quantity, self.user)
        orders.send_order(order, self.user)
        return order, line

    def payment(self, order, amount="25", session=None, method="CASH"):
        return payments.create_amount_payment(order, D(amount), method, self.user,
            cash_session=session, reference="REF" if method in ("TRANSFER", "DEPOSIT") else "", card_approved=method == "CARD")

    def close_session(self, session, counted=None, reason=""):
        cash.submit_blind_cash_count(session, cash.get_expected_cash(session) if counted is None else D(counted), self.user)
        return cash.close_cash_session(session, self.user, reason)
