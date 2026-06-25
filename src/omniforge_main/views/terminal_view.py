# src/omniforge_main/views/terminal_view.py
# ИСПРАВЛЕНО: Импорт ActionFactory, переопределение closeEvent вместо destroy
from __future__ import annotations

import pyte
from PySide6.QtWidgets import QWidget, QSizePolicy, QApplication
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtCore import QEvent
from PySide6.QtGui import (
    QPainter,
    QColor,
    QFont,
    QKeyEvent,
    QCloseEvent,
    QPaintEvent,
    QResizeEvent
)
from PySide6.QtGui import QPainter, QColor, QFont, QKeyEvent, QCloseEvent
from omniforge_main.ipc_client import IPCClient
from omniforge_api.ipc_protocol import TermOutputData
from omniforge_api.actions import ActionFactory # ИСПРАВЛЕНО: Добавлен импорт
from omniforge_api.models import TermSessionStatus
from omniforge_api.logger import get_logger
import time

SPECIAL_KEYS_MAP = {
    Qt.Key.Key_Up: b'\x1b[A', Qt.Key.Key_Down: b'\x1b[B',
    Qt.Key.Key_Right: b'\x1b[C', Qt.Key.Key_Left: b'\x1b[D',
    Qt.Key.Key_Home: b'\x1b[H', Qt.Key.Key_End: b'\x1b[F',
    Qt.Key.Key_PageUp: b'\x1b[5~', Qt.Key.Key_PageDown: b'\x1b[6~',
    Qt.Key.Key_Insert: b'\x1b[2~', Qt.Key.Key_Delete: b'\x1b[3~',
}

class TermDataEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())
    def __init__(self, data: bytes) -> None:
        super().__init__(self.EVENT_TYPE)
        self.data = data

class TerminalView(QWidget):
    create_session_requested = Signal(str, str)
    close_session_requested = Signal(str)

    def __init__(self, ipc_client: IPCClient) -> None:
        super().__init__()
        self.ipc_client = ipc_client
        self._log = get_logger("terminal_view")
        
        self.session_id: str | None = None
        self._active = False
        self._status: TermSessionStatus = TermSessionStatus.CONNECTING
        
        self._screen = pyte.HistoryScreen(80, 24, history=10000)
        self._stream = pyte.Stream(self._screen)
        
        self._pending_data = bytearray()
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(16) 
        self._flush_timer.timeout.connect(self._flush_pending_data)
        
        self.font = QFont("JetBrains Mono", 10)
        self.bg_color = QColor("#1E1E2E")
        self.fg_color = QColor("#CDD6F4")
        
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_status(self, status: TermSessionStatus) -> None:
        self._status = status
        if status == TermSessionStatus.EXITED:
            self._active = False
            self._flush_timer.stop()
            self.update()
        elif status == TermSessionStatus.RUNNING:
            self._active = True
            self._flush_timer.start()

    def start_session(self, session_id: str, cwd: str | None = None) -> None:
        if self.session_id == session_id: return
        
        if self.session_id:
            self.ipc_client.unsubscribe_from_term(self.session_id)
            
        self.session_id = session_id
        self._screen = pyte.HistoryScreen(80, 24, history=10000)
        self._stream = pyte.Stream(self._screen)
        self._pending_data.clear()
        
        self.ipc_client.subscribe_to_term(session_id, self.on_term_output)
        self.create_session_requested.emit(session_id, cwd)
        self.update()

    def on_term_output(self, data: TermOutputData) -> None:
        try:
            if self.isVisible():
                QApplication.postEvent(self, TermDataEvent(data.data))
        except RuntimeError:
            pass 

    def customEvent(self, event: TermDataEvent) -> None: # type: ignore
        if not self._active: return
        self._pending_data.extend(event.data)

    def _flush_pending_data(self) -> None:
        if not self._pending_data: return
        text = self._pending_data.decode('utf-8', errors='replace')
        self._pending_data.clear()
        self._stream.feed(text)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None: # type: ignore
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.bg_color)
        
        if not self.session_id or self._status == TermSessionStatus.CONNECTING:
            painter.setPen(self.fg_color); painter.setFont(self.font)
            painter.drawText(20, 50, "Starting terminal...")
            painter.end(); return
        elif self._status == TermSessionStatus.EXITED:
            painter.setPen(QColor("#F38BA8")); painter.setFont(self.font)
            painter.drawText(20, 50, f"Process exited. Session: {self.session_id}")
            painter.end(); return
            
        painter.setFont(self.font)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        char_width = metrics.horizontalAdvance("A")
        
        first_visible_line = 0
        last_visible_line = min(self._screen.lines, int(self.height() / line_height) + 1)
        
        for line_idx in range(first_visible_line, last_visible_line):
            if line_idx >= len(self._screen.display): break
            line = self._screen.display[line_idx]
            y = (line_idx * line_height) + line_height
            for char_idx, char in enumerate(line):
                if char == ' ': continue
                x = char_idx * char_width + 10
                painter.setPen(self.fg_color)
                painter.drawText(x, y, char)
                
        cursor = self._screen.cursor
        if cursor.visible:
            x = cursor.x * char_width + 10
            y = cursor.y * line_height + (line_height * 0.2)
            painter.fillRect(x, int(y), char_width, line_height, self.fg_color)
            
        painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._active or not self.session_id: return
        
        key = event.key()
        text = event.text()
        modifiers = event.modifiers()
        
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_C: self.ipc_client.send_term_input(b'\x03', self.session_id); return
            elif key == Qt.Key.Key_D: self.ipc_client.send_term_input(b'\x04', self.session_id); return
            elif key == Qt.Key.Key_Z: self.ipc_client.send_term_input(b'\x1a', self.session_id); return
            elif key == Qt.Key.Key_L: self.ipc_client.send_term_input(b'\x0c', self.session_id); return

        if key in SPECIAL_KEYS_MAP:
            self.ipc_client.send_term_input(SPECIAL_KEYS_MAP[key], self.session_id); return
            
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self.ipc_client.send_term_input(b'\r', self.session_id)
        elif key == Qt.Key.Key_Backspace:
            self.ipc_client.send_term_input(b'\x08', self.session_id) 
        elif key == Qt.Key.Key_Tab:
            self.ipc_client.send_term_input(b'\t', self.session_id)
        elif text:
            self.ipc_client.send_term_input(text.encode('utf-8'), self.session_id)

    def resizeEvent(self, event: QResizeEvent) -> None: # type: ignore
        super().resizeEvent(event)
        if not self.session_id: return
        metrics = self.fontMetrics()
        cols = max(1, self.width() // max(1, metrics.horizontalAdvance("A")))
        rows = max(1, self.height() // max(1, metrics.height()))
        if cols != self._screen.columns or rows != self._screen.lines:
            self._screen.resize(rows, cols)
            self._stream = pyte.Stream(self._screen)
            self.ipc_client.send_action_async(ActionFactory.create_term_resize(self.session_id, rows, cols))

    def closeEvent(self, event: QCloseEvent) -> None: # type: ignore
        # ИСПРАВЛЕНО: Очистка подписок при закрытии виджета
        if self.session_id:
            self._flush_timer.stop()
            self.ipc_client.unsubscribe_from_term(self.session_id)
        super().closeEvent(event)