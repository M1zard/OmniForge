# src/omniforge_api/ipc_action_handler.py
# Обновлен тип аргумента
from __future__ import annotations
from typing import Protocol, runtime_checkable
from omniforge_api.actions import Action

@runtime_checkable
class ActionHandler(Protocol):
    async def handle(self, action: Action) -> None:
        ...