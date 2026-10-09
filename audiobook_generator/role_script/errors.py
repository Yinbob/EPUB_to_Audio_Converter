"""稳定的结构化校验报告。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ErrorItem:
    code: str
    path: str
    message: str
    severity: str = "error"
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
            "context": dict(self.context),
        }


@dataclass
class ValidationReport:
    schema_version: Optional[int] = None
    errors: List[ErrorItem] = field(default_factory=list)
    warnings: List[ErrorItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, path: str, message: str, **context: Any) -> None:
        self.errors.append(ErrorItem(code, path, message, "error", context))

    def warn(self, code: str, path: str, message: str, **context: Any) -> None:
        self.warnings.append(ErrorItem(code, path, message, "warning", context))

    def extend(self, other: "ValidationReport") -> None:
        if other.schema_version is not None:
            self.schema_version = other.schema_version
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "schema_version": self.schema_version,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
        }
