from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from checkers.base import BaseChecker

_REGISTRY: dict[str, type[BaseChecker]] = {}


def register(name: str):
    """Decorator: @register("metadata") class MetadataChecker(BaseChecker): ..."""
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_checker(name: str) -> type[BaseChecker]:
    if name not in _REGISTRY:
        raise KeyError(f"No checker registered as '{name}'. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]


def all_checkers() -> dict[str, type[BaseChecker]]:
    return dict(_REGISTRY)
