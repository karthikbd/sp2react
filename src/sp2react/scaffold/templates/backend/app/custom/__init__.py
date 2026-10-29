"""Agent-written server code for behaviour the generic rule engine cannot express.

Each module here may define any of:
    def validate(ctx: dict) -> list[dict]          # extra errors: {"field", "message", "presentation"}
    def on_save(ctx: dict, item: dict, repo) -> None
    router: fastapi.APIRouter                      # custom endpoints (spec endpoints with custom=true)
and is bound to rules of kind "custom" through params.handler == module name.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

HANDLERS: dict[str, ModuleType] = {}


def load() -> dict[str, ModuleType]:
    for m in pkgutil.iter_modules(__path__):
        if not m.name.startswith("_"):
            HANDLERS[m.name] = importlib.import_module(f"{__name__}.{m.name}")
    return HANDLERS
