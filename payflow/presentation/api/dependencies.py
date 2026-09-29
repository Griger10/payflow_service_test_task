from typing import Annotated

from fastapi import Depends, Request

from payflow.application.interfaces import Clock, IdGenerator, UnitOfWorkFactory
from payflow.application.services import CreatePayment, GetPayment
from payflow.bootstrap.factories import make_create_payment, make_get_payment, make_uow_factory
from payflow.bootstrap.resources import Resources
from payflow.infra.config import ServiceConfig
from payflow.infra.integrations.clock import SystemClock
from payflow.infra.integrations.identifiers import UUID4Generator


def get_resources(request: Request) -> Resources:
    """The only place that touches lifespan state; everything else is built with Depends."""
    resources: Resources = request.state.resources
    return resources


ResourcesDep = Annotated[Resources, Depends(get_resources)]


def get_settings(resources: ResourcesDep) -> ServiceConfig:
    return resources.settings


SettingsDep = Annotated[ServiceConfig, Depends(get_settings)]


def get_clock() -> Clock:
    return SystemClock()


ClockDep = Annotated[Clock, Depends(get_clock)]


def get_id_generator() -> IdGenerator:
    return UUID4Generator()


IdGeneratorDep = Annotated[IdGenerator, Depends(get_id_generator)]


def get_uow_factory(resources: ResourcesDep) -> UnitOfWorkFactory:
    return make_uow_factory(resources.session_factory)


UowFactoryDep = Annotated[UnitOfWorkFactory, Depends(get_uow_factory)]


def get_create_payment(
    uow_factory: UowFactoryDep, clock: ClockDep, id_generator: IdGeneratorDep
) -> CreatePayment:
    return make_create_payment(uow_factory=uow_factory, clock=clock, id_generator=id_generator)


CreatePaymentDep = Annotated[CreatePayment, Depends(get_create_payment)]


def get_get_payment(uow_factory: UowFactoryDep) -> GetPayment:
    return make_get_payment(uow_factory=uow_factory)


GetPaymentDep = Annotated[GetPayment, Depends(get_get_payment)]
