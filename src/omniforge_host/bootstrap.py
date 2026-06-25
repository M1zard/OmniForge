# src/omniforge_host/bootstrap.py
# Интеграция TerminalService
from __future__ import annotations

import asyncio
from omniforge_host.state.store import Store
from omniforge_api.models import AppState
from omniforge_host.ipc_server import IPCServer
from omniforge_host.services.project_watcher import ProjectService
from omniforge_host.services.lsp_manager import LspManager
from omniforge_host.services.terminal_service import TerminalService
from omniforge_api.logger import configure_logging, get_logger

async def main_loop() -> None:
    configure_logging("HOST")
    log = get_logger("bootstrap")
    
    initial_state = AppState()
    store = Store(initial_state)
    
    project_service = ProjectService(store)
    lsp_manager = LspManager(store)
    
    server = IPCServer(store)
    
    # Создаем TerminalService и передаем ему PUB socket для стриминга
    terminal_service = TerminalService(store, server.pub_socket)
    
    server.register_handler(lsp_manager)
    server.register_handler(terminal_service)
    
    log.info("host_starting")
    await server.start()
    
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        log.info("host_shutting_down")
        project_service.stop()

def run_host() -> None:
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        pass