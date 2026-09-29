from typing import override
from uuid import UUID, uuid4

from payflow.application.interfaces import IdGenerator


class UUID4Generator(IdGenerator):
    @override
    def new_uuid(self) -> UUID:
        return uuid4()
