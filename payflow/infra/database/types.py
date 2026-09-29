from enum import StrEnum
from typing import override

from sqlalchemy import Dialect, String
from sqlalchemy.types import TypeDecorator


class StrEnumType[E: StrEnum](TypeDecorator[E]):
    """Stores a StrEnum as VARCHAR and returns enum members from queries."""

    impl = String  # type: ignore[mutable-override]
    cache_ok = True  # type: ignore[mutable-override]

    def __init__(self, enum_cls: type[E], length: int) -> None:
        super().__init__(length)
        self._enum_cls = enum_cls

    @override
    def process_bind_param(self, value: E | None, dialect: Dialect) -> str | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> E | None:
        return None if value is None else self._enum_cls(value)
