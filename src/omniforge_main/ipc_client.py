# src/omniforge_main/ipc_client.py
# ИСПРАВЛЕНО: Упрощена сериализация TermInput, убран двойной конверт
from __future__ import annotations

import zmq
import zmq.asyncio
import asyncio
import threading
from typing import get_type_hints, Callable
from pydantic import TypeAdapter
from PySide6.QtCore import QObject, Signal
from omniforge_api.types import SessionId
from omniforge_api.actions import Action
from omniforge_api.ipc_protocol import IPCChannel, IPCMessageType, IPCProtocol, StateDelta, TermInputData, TermOutputData
from omniforge_api.models import AppState
from omniforge_api.logger import get_logger

class StateBridge(QObject):
    state_updated = Signal(object) 

class IPCClient:
    def __init__(self, host: str = "127.0.0.1", command_port: int = 5555, state_port: int = 5556) -> None:
        self._host = host
        self._command_port = command_port
        self._state_port = state_port
        self._log = get_logger("ipc_client")
        
        self._context = zmq.asyncio.Context()
        self._dealer_socket = self._context.socket(zmq.DEALER)
        self._sub_socket = self._context.socket(zmq.SUB)
        self._sub_socket.setsockopt(zmq.SUBSCRIBE, b"state_delta")
        
        self._current_state: AppState = AppState()
        self.bridge = StateBridge()
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._data_callbacks: dict[bytes, Callable[[TermOutputData], None]] = {}

    async def start(self) -> None:
        self._dealer_socket.connect(f"tcp://{self._host}:{self._command_port}")
        self._sub_socket.connect(f"tcp://{self._host}:{self._state_port}")
        await asyncio.sleep(0.1)
        asyncio.create_task(self._listen_for_updates())

    def send_action_async(self, action: Action) -> None:
        if not self._async_loop: return
        asyncio.run_coroutine_threadsafe(self._send_action_internal(action), self._async_loop)

    async def _send_action_internal(self, action: Action) -> dict:
        action_bytes = IPCProtocol.encode(IPCChannel.COMMAND, IPCMessageType.ACTION, "", action.model_dump(mode='python'))
        await self._dealer_socket.send_multipart([b"", action_bytes])
        try:
            _, reply_bytes = await asyncio.wait_for(self._dealer_socket.recv_multipart(), timeout=2.0)
            _, reply_dict = IPCProtocol.decode(reply_bytes)
            return reply_dict
        except asyncio.TimeoutError:
            return {"error": "Timeout"}

    def send_term_input(self, data: bytes, session_id: str) -> None:
        if not self._async_loop: return
        input_data = TermInputData(session_id=session_id, data=data)
        asyncio.run_coroutine_threadsafe(self._send_term_input_internal(input_data), self._async_loop)

    async def _send_term_input_internal(self, data: TermInputData) -> None:
        # ИСПРАВЛЕНО: Единый формат Envelope, как и для обычных Action
        msg_bytes = IPCProtocol.encode(IPCChannel.COMMAND, IPCMessageType.TERM_INPUT, "", data.model_dump(mode='python'))
        await self._dealer_socket.send_multipart([b"", msg_bytes])

    def subscribe_to_term(self, session_id: str, callback: Callable[[TermOutputData], None]) -> None:
        topic = b"term_" + session_id.encode('utf-8')
        self._sub_socket.setsockopt(zmq.SUBSCRIBE, topic)
        self._data_callbacks[topic] = callback

    def unsubscribe_from_term(self, session_id: str) -> None:
        topic = b"term_" + session_id.encode('utf-8')
        self._sub_socket.setsockopt(zmq.UNSUBSCRIBE, topic)
        self._data_callbacks.pop(topic, None)

    async def _listen_for_updates(self) -> None:
        while True:
            try:
                topic, payload_bytes = await self._sub_socket.recv_multipart()
                # ДЕБАГ ПРИНТ 1: Проверяем, прилетает ли вообще что-то по сети
                print(f"[DEBUG CLIENT] Получен ZMQ пакет! Топик: {topic}, Размер байт: {len(payload_bytes)}")
                
                if topic == b"state_delta":
                    _, payload_dict = IPCProtocol.decode(payload_bytes)
                    delta = StateDelta.model_validate(payload_dict)
                    self._apply_delta(delta)
                elif topic.startswith(b"term_"):
                    if topic in self._data_callbacks:
                        payload_dict = IPCProtocol.decode_data_channel(payload_bytes)
                        output_data = TermOutputData.model_validate(payload_dict)
                        self._data_callbacks[topic](output_data)
                    
            except zmq.ZMQError:
                if self._context.closed: break
            except Exception as e:
                # ДЕБАГ ПРИНТ 2: Выводим ошибку парсинга прямо в терминал
                print(f"[DEBUG CLIENT ERROR] Ошибка в цикле обновлений: {e}")
                self._log.error("update_processing_error", exc_info=e)

    def _apply_delta(self, delta: StateDelta) -> None:
        # ДЕБАГ ПРИНТ 3: Проверяем, какие ключи прилетели в дельте
        print(f"[DEBUG CLIENT] Применили дельту. Измененные ключи: {delta.changed_keys}. Содержимое patches: {list(delta.patches.keys())}")
        
        update_dict: dict[str, object] = {}
        type_hints = get_type_hints(AppState)
        
        for key in delta.changed_keys:
            if key not in type_hints or key not in delta.patches:
                continue
                
            raw_patch = delta.patches[key]
            if isinstance(raw_patch, dict) and "value" in raw_patch and len(raw_patch) == 1:
                current_value = raw_patch["value"]
            else:
                current_value = raw_patch

            try:
                current_sub_state = getattr(self._current_state, key)
                
                if hasattr(current_sub_state, "model_validate") and isinstance(current_value, dict):
                    existing_data = current_sub_state.model_dump(mode="python")
                    existing_data.update(current_value)
                    update_dict[key] = current_sub_state.model_validate(existing_data)
                else:
                    adapter = TypeAdapter(type_hints[key])
                    update_dict[key] = adapter.validate_python(current_value)
                    
            except Exception as e:
                # ДЕБАГ ПРИНТ 4: Самое важное место падения валидатора
                print(f"[DEBUG CLIENT ERROR] Валидация ключа {key} упала! Ошибка: {e}")
                self._log.error(f"Failed to parse delta for key {key}. Patch: {current_value}", exc_info=e)
                
        if update_dict:
            self._current_state = self._current_state.model_copy(update=update_dict)
            # ДЕБАГ ПРИНТ 5: Пошел ли сигнал в GUI
            print(f"[DEBUG CLIENT] Отправляем сигнал state_updated в Qt")
            self.bridge.state_updated.emit(self._current_state)

    async def stop(self) -> None:
        self._dealer_socket.close(linger=0)
        self._sub_socket.close(linger=0)
        self._context.term()
        
    def set_async_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._async_loop = loop