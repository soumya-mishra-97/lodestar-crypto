"""Convert domain dataclasses into JSON-safe structures for storage and the API."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID


def to_json_dict(obj: Any) -> dict[str, Any]:
    """to_jsonable for values known to serialise to a JSON object."""
    return cast(dict[str, Any], to_jsonable(obj))


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [to_jsonable(v) for v in obj]
    return obj
