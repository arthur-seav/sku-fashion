"""Payment provider adapter (FR-X11).

Order logic only talks to the `PaymentProvider` interface. Adding a method
(e.g. an online gateway, out of scope #02) means writing one subclass and
registering it — checkout and order code stay unchanged.
"""

from abc import ABC, abstractmethod

from django.conf import settings

from orders.models import OrderStatus

from .models import Payment


class UnknownProvider(Exception):
    pass


class PaymentProvider(ABC):
    code = ""
    label = ""
    description = ""
    requires_receipt = False

    @property
    @abstractmethod
    def initial_order_status(self):
        """Order status right after checkout (FR-X08)."""

    def create_payment(self, order):
        return Payment.objects.create(order=order, provider=self.code, amount=order.grand_total,
                                      currency=order.currency, status=Payment.Status.PENDING)

    @abstractmethod
    def instructions(self, payment):
        """What the customer must do next, shown on the confirmation page."""


class CashOnDeliveryProvider(PaymentProvider):
    code = "COD"
    label = "Cash on delivery"
    description = "Pay the courier in cash when the parcel arrives."

    @property
    def initial_order_status(self):
        return OrderStatus.PREPARING

    def instructions(self, payment):
        return f"Please have {payment.currency} {payment.amount} ready for the courier."


class BankTransferProvider(PaymentProvider):
    code = "BANK_TRANSFER"
    label = "Bank transfer"
    description = "Transfer to the store's bank account, then upload the receipt."
    requires_receipt = True

    @property
    def initial_order_status(self):
        return OrderStatus.PENDING_PAYMENT

    @staticmethod
    def bank_details():
        return {
            "bank": settings.STORE_BANK_NAME,
            "account_name": settings.STORE_BANK_ACCOUNT_NAME,
            "account_no": settings.STORE_BANK_ACCOUNT_NO,
        }

    def instructions(self, payment):
        d = self.bank_details()
        return (f"Transfer {payment.currency} {payment.amount} to {d['bank']}, account {d['account_no']} "
                f"({d['account_name']}), with reference {payment.order.order_no}. Upload the receipt within "
                f"24 hours or the order is cancelled automatically.")


class ProviderRegistry:
    def __init__(self, providers):
        self._providers = {p.code: p for p in providers}

    def get(self, code):
        try:
            return self._providers[code]
        except KeyError:
            raise UnknownProvider(f"Unknown payment method: {code}") from None

    def all(self):
        return list(self._providers.values())

    def choices(self):
        return [(p.code, p.label) for p in self._providers.values()]


registry = ProviderRegistry([CashOnDeliveryProvider(), BankTransferProvider()])
