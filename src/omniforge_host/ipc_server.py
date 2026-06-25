# src/omniforge_host/ipc_server.py
# ФИКС: Использование ZMQ Topic b"state_delta" для State Channel
from __future__ import annotations

import asyncio
import zmq
import zmq.asyncio
from omniforge_api.types import SessionId, generate_session_id
from omniforge_api.actions import Action, ActionType, InitSessionAction
from omniforge_api.ipc_protocol import IPCChannel, IPCMessageType, IPCProtocol, StateDelta, TermInputData
from omniforge_api.ipc_action_handler import ActionHandler
from omniforge_host.state.store import Store
from omniforge_api.models import AppState
from omniforge_api.logger import get_logger

class IPCServer:
    def __init__(self, store: Store, host: str = "127.0.0.1", command_port: int = 5555, state_port: int = 5556) -> None:
        self._store = store
        self._host = host
        self._command_port = command_port
        self._state_port = state_port
        self._session_id = generate_session_id()
        self._log = get_logger("ipc_server")
        
        self._context = zmq.asyncio.Context()
        self._router_socket = self._context.socket(zmq.ROUTER)
        self._pub_socket = self._context.socket(zmq.PUB)
        
        self._store.subscribe(self._on_state_changed)
        self._action_handlers: list[ActionHandler] = []

    @property
    def pub_socket(self) -> zmq.asyncio.Socket:
        return self._pub_socket

    def register_handler(self, handler: ActionHandler) -> None:
        self._action_handlers.append(handler)

    async def start(self) -> None:
        self._router_socket.bind(f"tcp://{self._host}:{self._command_port}")
        self._pub_socket.bind(f"tcp://{self._host}:{self._state_port}")
        
        init_action = InitSessionAction(session_id=self._session_id)
        await self._store.dispatch(init_action)
        self._log.info("ipc_server_started", ports=(self._command_port, self._state_port))
        
        asyncio.create_task(self._listen_for_commands())

    async def _listen_for_commands(self) -> None:
        while True:
            try:
                msg_parts = await self._router_socket.recv_multipart()
                if len(msg_parts) != 3: continue
                
                identity, _, payload_bytes = msg_parts
                envelope, payload_dict = IPCProtocol.decode(payload_bytes)
                
                if envelope.message_type == IPCMessageType.TERM_INPUT:
                    input_data = TermInputData.model_validate(payload_dict)
                    for handler in self._action_handlers:
                        if hasattr(handler, 'handle_input'):
                            await handler.handle_input(input_data) # type: ignore
                else:
                    action = IPCProtocol.decode_action(payload_dict)
                    for handler in self._action_handlers:
                        await handler.handle(action)
                        
                    if action.action_type != ActionType.LSP_COMPLETION_REQUEST:
                        await self._store.dispatch(action)
            
            except zmq.ZMQError as e:
                if self._context.closed: break
                self._log.error("zmq_error_listening", exc_info=e)
            except Exception as e:
                self._log.error("command_processing_error", exc_info=e)

    async def _on_state_changed(self, state: AppState, changed_keys: set[str]) -> None:
        patches: dict[str, dict] = {}
        for key in changed_keys:
            if key not in AppState.model_fields:
                continue

            value = getattr(state, key)

            try:
                if hasattr(value, "model_dump"):
                    # Принудительно проверяем, может ли Pydantic сдампить эту ветку стейта
                    patches[key] = value.model_dump(mode="python")
                else:
                    patches[key] = {"value": value}
            except Exception as serialization_error:
                # ЕСЛИ ТУТ УПАДЕТ — МЫ СРАЗУ УВИДИМ ЭТО В ТЕРМИНАЛЕ!
                print(f"\n[CRITICAL SERVER ERROR] Не удалось сериализовать ветку '{key}'!")
                print(f"Ошибка: {serialization_error}\n")
                raise serialization_error
        
        if not patches:
            return

        delta = StateDelta(changed_keys=list(changed_keys), patches=patches)
        delta_bytes = IPCProtocol.encode(IPCChannel.STATE_PUB, IPCMessageType.STATE_UPDATE_DELTA, self._session_id, delta.model_dump(mode='python'))
        
        # Печатаем размер отправляемого дерева для контроля
        if "project" in patches:
            print(f"[SERVER DEBUG] Отправляем дерево проекта на клиент! Размер пакета: {len(delta_bytes)} байт.")
            
        await self._pub_socket.send_multipart([b"state_delta", delta_bytes])

    async def stop(self) -> None:
        self._router_socket.close(linger=0)
        self._pub_socket.close(linger=0)
        self._context.term()