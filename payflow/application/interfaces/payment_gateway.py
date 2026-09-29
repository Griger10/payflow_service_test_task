from typing import Protocol

from payflow.domain import Payment
from payflow.domain.enums import PaymentStatus


class PaymentGateway(Protocol):
    async def process(self, payment: Payment) -> PaymentStatus:
        pass
