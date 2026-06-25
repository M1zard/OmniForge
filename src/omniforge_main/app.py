
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import uuid

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from omniforge_api.actions import ActionFactory
from omniforge_api.logger import configure_logging, get_logger
from omniforge_api.models import AppState, TermSessionStatus
from omniforge_main.ipc_client import IPCClient
from omniforge_main.views.editor_view import EditorView
from omniforge_main.views.project_explorer import ProjectExplorer
from omniforge_main.views.terminal_view import TerminalView


class OmniForgeMainWindow(QMainWindow):
    def __init__(self, ipc_client: IPCClient) -> None:
        super().__init__()
        self.ipc_client = ipc_client
        self.setWindowTitle("OmniForge V2 - Dark Forge Edition")
        self.resize(1280, 720)
        self._log = get_logger("main_window")
        
        self.project_explorer = ProjectExplorer()
        self.editor_view = EditorView(self.ipc_client)
        self.terminal_view = TerminalView(self.ipc_client)
        
        self.open_term_btn = QPushButton("Open Terminal")
        self.open_term_btn.setStyleSheet("background-color: #313244; color: #CDD6F4; padding: 5px;")
        self.open_term_btn.clicked.connect(self._open_new_terminal)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)
        
        left_panel = QVBoxLayout()
        left_panel.addWidget(self.project_explorer, stretch=9)
        left_panel.addWidget(self.open_term_btn, stretch=1)
        
        right_panel = QVBoxLayout()
        right_panel.addWidget(self.editor_view, stretch=7)
        right_panel.addWidget(self.terminal_view, stretch=3)
        
        main_layout.addLayout(left_panel, stretch=2)
        main_layout.addLayout(right_panel, stretch=8)
        
        self.setStyleSheet("QMainWindow { background-color: #181825; }")
        self.ipc_client.bridge.state_updated.connect(self.on_state_updated)
        self.terminal_view.create_session_requested.connect(self._create_term_session)

    def on_state_updated(self, state: object) -> None:
        if isinstance(state, AppState):
            self.project_explorer.update_tree(state.project.tree)
            self.editor_view.update_state(state.editor, state.lsp)

            if state.terminal.active_session_id:
                session = state.terminal.sessions.get(state.terminal.active_session_id)
                if session:
                    self.terminal_view.update_status(session.status)

    def _open_new_terminal(self) -> None:
        session_id = str(uuid.uuid4())
        self.terminal_view.start_session(session_id, None)

    def _create_term_session(self, session_id: str, cwd: str | None) -> None:
        action = ActionFactory.create_term_create(session_id, cwd)
        self.ipc_client.send_action_async(action)


class OmniForgeApp:
    def __init__(self) -> None:
        self.host_process: subprocess.Popen | None = None
        self.ipc_client: IPCClient | None = None
        self.qt_app: QApplication | None = None
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._log = get_logger("app")

    def run(self) -> int:
        configure_logging("MAIN")
        self.host_process = subprocess.Popen([sys.executable, "-m", "omniforge_host"])
        
        self.qt_app = QApplication(sys.argv)
        self.ipc_client = IPCClient()
        
        self._start_async_loop()
        
        main_window = OmniForgeMainWindow(self.ipc_client)
        main_window.show()
        
        QTimer.singleShot(2000, self._send_project_open_action)

        result = self.qt_app.exec()
        self._cleanup()
        return result

    def _start_async_loop(self) -> None:
        self._async_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(target=self._async_loop.run_forever, daemon=True)
        self._async_thread.start()
        
        self.ipc_client.set_async_loop(self._async_loop)
        
        future = asyncio.run_coroutine_threadsafe(self.ipc_client.start(), self._async_loop)
        try:
            future.result(timeout=5.0)
        except Exception as e:
            self._log.error("Failed to connect to host on startup", exc_info=e)

    def _send_project_open_action(self) -> None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        action = ActionFactory.create_project_open(root)
        self.ipc_client.send_action_async(action)

    def _cleanup(self) -> None:
        if self.ipc_client and self._async_loop:
            future = asyncio.run_coroutine_threadsafe(self.ipc_client.stop(), self._async_loop)
            try:
                future.result(timeout=2.0)
            except Exception:
                pass
                
        if self.host_process:
            self.host_process.terminate()
            self.host_process.wait()


if __name__ == "__main__":
    app = OmniForgeApp()
    sys.exit(app.run())
