# src/omniforge_host/services/lsp_client.py
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Coroutine
from omniforge_api.logger import get_logger

class LspClient:
    """Низкоуровневый клиент для общения с LSP сервером через stdio (JSON-RPC 2.0)."""
    
    def __init__(self, command: list[str], root_path: str) -> None:
        self._command = command
        self._root_path = root_path
        self._process: asyncio.subprocess.Process | None = None
        self._request_futures: dict[str, asyncio.Future] = {}
        self._notification_handlers: dict[str, Callable[[dict], Coroutine]] = {}
        self._log = get_logger("lsp_client")
        self._writer_lock = asyncio.Lock()
        
    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())
        
        # Initialize Request
        init_params = {
            "processId": None,
            "rootUri": self._path_to_uri(self._root_path),
            "capabilities": {}
        }
        await self.send_request("initialize", init_params)
        await self.send_notification("initialized", {})

    def on_notification(self, method: str, handler: Callable[[dict], Coroutine]) -> None:
        self._notification_handlers[method] = handler

    async def send_request(self, method: str, params: dict) -> Any:
        if not self._process or not self._process.stdin:
            return None
            
        request_id = str(uuid.uuid4())
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }
        
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._request_futures[request_id] = future
        
        await self._send_message(message)
        
        try:
            return await asyncio.wait_for(future, timeout=10.0)
        except asyncio.TimeoutError:
            self._log.error("LSP request timeout", method=method)
            return None

    async def send_notification(self, method: str, params: dict) -> None:
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self._send_message(message)

    async def _send_message(self, message: dict) -> None:
        if not self._process or not self._process.stdin:
            return
        async with self._writer_lock:
            body = json.dumps(message)
            header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
            self._process.stdin.write(header.encode('utf-8') + body.encode('utf-8'))
            await self._process.stdin.drain()

    async def _read_stdout(self) -> None:
        if not self._process or not self._process.stdout:
            return
        while True:
            try:
                # Read headers
                headers = {}
                while True:
                    line_bytes = await self._process.stdout.readline()
                    if not line_bytes or line_bytes == b'\r\n':
                        break
                    line = line_bytes.decode('utf-8').strip()
                    if ':' in line:
                        key, val = line.split(':', 1)
                        headers[key.strip()] = val.strip()
                
                content_length = int(headers.get('Content-Length', 0))
                if content_length == 0:
                    continue
                    
                # Read body
                body_bytes = await self._process.stdout.readexactly(content_length)
                message = json.loads(body_bytes.decode('utf-8'))
                await self._handle_message(message)
                
            except asyncio.IncompleteReadError:
                self._log.info("LSP server closed stdout")
                break
            except Exception as e:
                self._log.error("Error reading LSP stdout", exc_info=e)
                break

    async def _read_stderr(self) -> None:
        if not self._process or not self._process.stderr:
            return
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            # Логируем stderr LSP сервера для отладки
            # self._log.debug(f"LSP STDERR: {line.decode('utf-8').strip()}")

    async def _handle_message(self, message: dict) -> None:
        if "id" in message:
            # Response
            request_id = message["id"]
            if request_id in self._request_futures:
                future = self._request_futures.pop(request_id)
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"]))
                else:
                    future.set_result(message.get("result"))
        elif "method" in message:
            # Notification
            method = message["method"]
            if method in self._notification_handlers:
                handler = self._notification_handlers[method]
                await handler(message.get("params", {}))

    @staticmethod
    def _path_to_uri(path: str) -> str:
        # Упрощенная конвертация для Linux/Mac, для Windows нужен file:///C:/...
        import os
        return f"file://{os.path.abspath(path)}"

    @staticmethod
    def uri_to_path(uri: str) -> str:
        if uri.startswith("file://"):
            return uri[7:]
        return uri