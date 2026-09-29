from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from payflow.application.dto import CreatePaymentCommand
from payflow.application.errors import IdempotencyConflictError, PaymentNotFoundError
from payflow.presentation.api.dependencies import CreatePaymentDep, GetPaymentDep
from payflow.presentation.api.schemas import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    PaymentResponse,
)
from payflow.presentation.api.security import require_api_key

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_payment(
    body: CreatePaymentRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    use_case: CreatePaymentDep,
) -> CreatePaymentResponse:
    try:
        result = await use_case.execute(
            CreatePaymentCommand(
                amount=body.amount,
                currency=body.currency,
                description=body.description,
                metadata=body.metadata,
                webhook_url=str(body.webhook_url),
                idempotency_key=idempotency_key,
            ),
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key already belongs to another payment request",
        ) from exc
    return CreatePaymentResponse(
        payment_id=result.payment_id,
        status=result.status,
        created_at=result.created_at,
    )


@router.get("/{payment_id}")
async def get_payment(
    payment_id: UUID,
    query: GetPaymentDep,
) -> PaymentResponse:
    try:
        payment = await query.execute(payment_id)
    except PaymentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        ) from exc
    return PaymentResponse(
        payment_id=payment.payment_id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=dict(payment.metadata),
        status=payment.status,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )
