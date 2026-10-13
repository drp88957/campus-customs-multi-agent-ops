"""Append-only JSONL audit trail for agent-loop steps."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
import json
from pathlib import Path
import threading
from typing import Any

from pydantic import BaseModel


_AUDIT_WRITE_LOCK = threading.Lock()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: to_jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AuditTrail:
    """Write one JSON object per line, always opening the file in append mode."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"logged_at": datetime.now(timezone.utc).isoformat(), **event}
        line = json.dumps(to_jsonable(record), ensure_ascii=False, separators=(",", ":"))
        with _AUDIT_WRITE_LOCK, self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
