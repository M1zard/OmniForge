# src/omniforge_api/types.py
from __future__ import annotations

import uuid 
from typing import NewType
from pydantic import BaseModel, ConfigDict

# Строго типизированные алиасы для предотвращения случайной передачи неверных ID
SessionId = NewType("SessionId", str)
ActionId = NewType("ActionId", str)
Timestamp = NewType("Timestamp", float)

def generate_action_id() -> ActionId:
    return ActionId(str(uuid.uuid4()))

def generate_session_id() -> SessionId:
    return SessionId(str(uuid.uuid4()))

class StrictModel(BaseModel):
    """Базовая модель для всех DTO в OmniForge. Запрещает лишние поля."""
    model_config = ConfigDict(extra="forbid", frozen=True)
