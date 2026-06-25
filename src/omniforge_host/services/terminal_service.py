# src/omniforge_host/services/terminal_service.py
# ИСПРАВЛЕНО: ZMQ Thread Safety через asyncio.Queue
from __future__ import annotations

import asyncio
import os
import zmq
from omniforge_host.state.store import Store
from omniforge_api.actions import (
    Action, TermCreateAction, TermCloseAction, TermResizeAction, 
    TermExitedAction, TermStatusUpdateAction
)
from omniforge_api.ipc_action_handler import ActionHandler
from omniforge_api.models import TermSessionStatus
from omniforge_api.ipc_protocol import IPCChannel, IPCMessageType, IPCProtocol, StateDelta, TermInputData, TermOutputData
from omniforge_host.services.pty_interface import PTYInterface, create_pty
from omniforge_api.logger import get_logger

class TerminalService(ActionHandler):
    def __init__(self, store: Store, zmq_pub_socket: zmq.asyncio.Socket) -> None:
        self._store = store
        self._pub_socket = zmq_pub_socket
        self._log = get_logger("terminal_service")
        self._sessions: dict[str, PTYInterface] = {}
        self._session_tasks: dict[str, asyncio.Task] = {}
        
        # ИСПРАВЛЕНО: Очередь для безопасной пересылки данных из потоков PTY в asyncio ZMQ
        self._output_queue: asyncio.Queue[tuple[bytes, bytes]] = asyncio.Queue()
        self._output_task = asyncio.create_task(self._drain_output_queue())

    async def _drain_output_queue(self) -> None:
        """Асинхронный воркер, безопасно отправляющий данные в ZMQ PUB сокет."""
        while True:
            topic, msg = await self._output_queue.get()
            try:
                await self._pub_socket.send_multipart([topic, msg])
            except zmq.ZMQError:
                self._log.warning("Failed to send term data via ZMQ")
            except asyncio.CancelledError:
                break

    async def handle(self, action: Action) -> None:
        match action:
            case TermCreateAction(session_id=sid, shell=sh, cwd=cwd):
                await self._create_session(sid, sh, cwd)
            case TermCloseAction(session_id=sid):
                await self._close_session(sid)
            case TermResizeAction(session_id=sid, rows=r, cols=c):
                self._resize_session(sid, r, c)

    async def handle_input(self, data: TermInputData) -> None:
        session = self._sessions.get(data.session_id)
        if session:
            await asyncio.to_thread(session.write, data.data)

    async def _create_session(self, session_id: str, shell: str | None, cwd: str | None) -> None:
        if session_id in self._sessions: return
        
        loop = asyncio.get_running_loop()

        def on_data(sid: str, data: bytes) -> None:
            # Потокобезопасная отправка в очередь
            output_data = TermOutputData(session_id=sid, data=data)
            msg = IPCProtocol.encode_data_channel(IPCMessageType.TERM_OUTPUT, output_data)
            topic = b"term_" + sid.encode('utf-8')
            loop.call_soon_threadsafe(self._output_queue.put_nowait, (topic, msg))

        def on_exit(sid: str, exit_code: int) -> None:
            asyncio.run_coroutine_threadsafe(self._handle_pty_exit(sid, exit_code), loop)

        pty_instance = create_pty(
            shell=shell, cwd=cwd, rows=24, cols=80,
            on_exit=lambda ec, sid=session_id: on_exit(sid, ec),
            on_data=on_data,
            session_id=session_id
        )
        self._sessions[session_id] = pty_instance
        
        await self._store.dispatch(TermStatusUpdateAction(session_id=session_id, pid=pty_instance.pid))
        
        if hasattr(pty_instance, 'master_fd'):
            task = asyncio.create_task(self._read_unix_pty_output(session_id, pty_instance))
            self._session_tasks[session_id] = task

    async def _read_unix_pty_output(self, session_id: str, pty: PTYInterface) -> None:
        loop = asyncio.get_running_loop()
        fd = getattr(pty, 'master_fd', -1)
        if fd == -1: return

        def read_callback() -> None:
            try:
                data = os.read(fd, 65536)
                if data:
                    pty._on_data(session_id, data)
                else:
                    loop.remove_reader(fd)
            except OSError:
                loop.remove_reader(fd)

        loop.add_reader(fd, read_callback)
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            loop.remove_reader(fd)

    async def _close_session(self, session_id: str) -> None:
        pty_instance = self._sessions.pop(session_id, None)
        task = self._session_tasks.pop(session_id, None)
        
        if task:
            task.cancel()
            
        if pty_instance:
            await asyncio.to_thread(pty_instance.close)

    def _resize_session(self, session_id: str, rows: int, cols: int) -> None:
        session = self._sessions.get(session_id)
        if session:
            try:
                session.resize(rows, cols)
            except Exception as e:
                self._log.error("Resize failed", exc_info=e)

    async def _handle_pty_exit(self, session_id: str, exit_code: int) -> None:
        if session_id not in self._sessions:
            current_state = self._store.state.terminal.sessions.get(session_id)
            if current_state and current_state.status != TermSessionStatus.EXITED:
                await self._store.dispatch(TermExitedAction(session_id=session_id, exit_code=exit_code))
            return
            
        await self._store.dispatch(TermExitedAction(session_id=session_id, exit_code=exit_code))
        await self._close_session(session_id)