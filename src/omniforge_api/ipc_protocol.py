# src/omniforge_api/ipc_protocol.py
from __future__ import annotations

from enum import IntEnum, StrEnum
import msgpack
from pydantic import BaseModel, ConfigDict, TypeAdapter
from omniforge_api.types import SessionId
from omniforge_api.actions import Action
from typing import Any

class IPCChannel(IntEnum):
    COMMAND = 1
    STATE_PUB = 2
    EXT_HOST = 3

class IPCMessageType(StrEnum):
    ACTION = "action"
    STATE_UPDATE_FULL = "state_update_full"
    STATE_UPDATE_DELTA = "state_update_delta"
    ERROR = "error"
    ACK = "ack"
    
    # Data Channel Message Types
    TERM_INPUT = "term.input"     # UI -> Host (stdin)
    TERM_OUTPUT = "term.output"   # Host -> UI (stdout/stderr)

class IPCEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    channel: IPCChannel
    message_type: IPCMessageType
    session_id: SessionId
    payload: bytes

class StateDelta(BaseModel):
    model_config = ConfigDict(frozen=True)
    changed_keys: list[str]
    patches: dict[str, Any] 

ActionAdapter = TypeAdapter(Action)

# --- DATA CHANNEL CONTRACTS ---
class TermInputData(BaseModel):
    """Формат данных для ввода в терминал (stdin)."""
    model_config = ConfigDict(frozen=True)
    session_id: str
    data: bytes

class TermOutputData(BaseModel):
    """Формат данных для вывода из терминала (stdout/stderr)."""
    model_config = ConfigDict(frozen=True)
    session_id: str
    data: bytes

class IPCProtocol:
    @staticmethod
    def encode(
        channel: IPCChannel, 
        message_type: IPCMessageType, 
        session_id: SessionId, 
        data: dict | BaseModel
    ) -> bytes:
        if isinstance(data, BaseModel):
            data_dict = data.model_dump(mode='python')
        else:
            data_dict = data
            
        payload_bytes = msgpack.packb(data_dict, use_bin_type=True)
        envelope = IPCEnvelope(
            channel=channel,
            message_type=message_type,
            session_id=session_id,
            payload=payload_bytes
        )
        return msgpack.packb(envelope.model_dump(mode='python'), use_bin_type=True)

    @staticmethod
    def decode(raw_bytes: bytes) -> tuple[IPCEnvelope, dict]:
        raw_envelope_dict = msgpack.unpackb(raw_bytes, raw=False)
        envelope = IPCEnvelope(**raw_envelope_dict)
        payload_dict = msgpack.unpackb(envelope.payload, raw=False)
        return envelope, payload_dict

    @staticmethod
    def decode_action(payload_dict: dict) -> Action:
        return ActionAdapter.validate_python(payload_dict)
    
    @staticmethod
    def encode_data_channel(message_type: IPCMessageType, data: BaseModel) -> bytes:
        """Специальная кодировка для Data Channel без оверхеда Envelope."""
        return msgpack.packb(data.model_dump(mode='python'), use_bin_type=True)

    @staticmethod
    def decode_data_channel(raw_bytes: bytes) -> dict:
        return msgpack.unpackb(raw_bytes, raw=False)