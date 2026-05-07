from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CheckFinding:
    checker: str
    passed: bool
    severity: str  # "error" | "warning" | "info"
    message: str
    details: dict = field(default_factory=dict)


class BaseChecker(ABC):
    def __init__(self, config) -> None:
        self._config = config

    @abstractmethod
    def run(self, file_path: Path) -> list[CheckFinding]:
        ...

    def _finding(
        self,
        passed: bool,
        severity: str,
        message: str,
        details: Optional[dict] = None,
    ) -> CheckFinding:
        name = type(self).__name__.lower().replace("checker", "")
        return CheckFinding(
            checker=name,
            passed=passed,
            severity=severity,
            message=message,
            details=details or {},
        )
