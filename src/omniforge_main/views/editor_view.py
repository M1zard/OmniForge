# src/omniforge_main/views/editor_view.py
# РЕШЕНИЕ ДЕФЕКТА 5: Использование публичного API IPCClient
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QKeyEvent
from omniforge_api.models import EditorState, EditorBuffer, LspState, Diagnostic, DiagnosticSeverity
from omniforge_api.actions import ActionFactory
from omniforge_main.ipc_client import IPCClient
from omniforge_api.logger import get_logger

class EditorView(QWidget):
    def __init__(self, ipc_client: IPCClient) -> None:
        super().__init__()
        self.ipc_client = ipc_client
        self._log = get_logger("editor_view")
        
        self.current_buffer: EditorBuffer | None = None
        self.lsp_state: LspState | None = None
        self.cursor_offset: int = 0
        
        self.font = QFont("JetBrains Mono", 10)
        self.bg_color = QColor("#1E1E2E")
        self.text_color = QColor("#CDD6F4")
        self.cursor_color = QColor("#89B4FA")
        self.error_color = QColor("#F38BA8")
        self.warning_color = QColor("#F9E2AF")
        
        self.cursor_visible = True
        self.cursor_timer = QTimer(self)
        self.cursor_timer.timeout.connect(self._blink_cursor)
        self.cursor_timer.start(500)
        
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_state(self, editor_state: EditorState, lsp_state: LspState) -> None:
        self.lsp_state = lsp_state
        if editor_state.active_file_id and editor_state.active_file_id in editor_state.open_buffers:
            new_buffer = editor_state.open_buffers[editor_state.active_file_id]
            if new_buffer is not self.current_buffer:
                self.cursor_offset = len(new_buffer.content)
            self.current_buffer = new_buffer
            self.update()
        elif not editor_state.active_file_id:
            self.current_buffer = None
            self.update()

    def paintEvent(self, event: PySide6.QtGui.QPaintEvent) -> None: # type: ignore
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.bg_color)
        
        if not self.current_buffer:
            painter.setPen(self.text_color)
            painter.setFont(self.font)
            painter.drawText(20, 50, "No file open. Action: Project opened automatically.")
            painter.end()
            return
            
        painter.setFont(self.font)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        
        lines = self.current_buffer.content.split('\n')
        
        y = line_height + 10
        current_offset = 0
        
        for i, line in enumerate(lines):
            painter.setPen(QPen(self.text_color))
            painter.drawText(20, y, line)
            
            if self.lsp_state:
                file_id = self.current_buffer.file_id
                diags = self.lsp_state.diagnostics.get(file_id, [])
                for diag in diags: 
                    line_start_offset = current_offset
                    line_end_offset = current_offset + len(line)
                    
                    if diag.start_offset >= line_start_offset and diag.start_offset < line_end_offset:
                        char_offset = diag.start_offset - line_start_offset
                        char_len = max(1, diag.end_offset - diag.start_offset)
                        
                        x_start = metrics.horizontalAdvance(line[:char_offset]) + 20
                        x_width = metrics.horizontalAdvance(line[char_offset:char_offset+char_len])
                        
                        color = self.error_color if diag.severity == DiagnosticSeverity.ERROR else self.warning_color
                        pen = QPen(color, 2, Qt.PenStyle.DotLine)
                        painter.setPen(pen)
                        painter.drawLine(x_start, y + 2, x_start + x_width, y + 2)
                        
            current_offset += len(line) + 1
            y += line_height
            
        self._draw_cursor(painter, metrics, lines, line_height)
        self._draw_completion_hint(painter, metrics, line_height)
        
        painter.end()

    def _draw_cursor(self, painter: QPainter, metrics: QFontMetrics, lines: list[str], line_height: int) -> None:
        if not self.cursor_visible: return
        current_offset = 0
        for i, line in enumerate(lines):
            if current_offset + len(line) >= self.cursor_offset:
                col = self.cursor_offset - current_offset
                x = metrics.horizontalAdvance(line[:col]) + 20
                y = (i * line_height) + 10
                painter.setPen(Qt.PenStyle.NoPen)
                painter.fillRect(x, y, 2, line_height, self.cursor_color)
                return
            current_offset += len(line) + 1

    def _draw_completion_hint(self, painter: QPainter, metrics: QFontMetrics, line_height: int) -> None:
        if not self.lsp_state or not self.current_buffer: return
        if self.cursor_offset == self.lsp_state.active_completion_offset and self.lsp_state.completions:
            painter.setPen(QPen(self.text_color))
            painter.setFont(self.font)
            
            current_offset = 0
            lines = self.current_buffer.content.split('\n')
            for i, line in enumerate(lines):
                if current_offset + len(line) >= self.cursor_offset:
                    col = self.cursor_offset - current_offset
                    x = metrics.horizontalAdvance(line[:col]) + 20
                    y = (i * line_height) + 10 + line_height
                    painter.fillRect(x, y, 250, len(self.lsp_state.completions[:5]) * line_height + 5, QColor("#313244"))
                    for idx, item in enumerate(self.lsp_state.completions[:5]):
                        painter.drawText(x + 5, y + (idx + 1) * line_height, item.label)
                    return
                current_offset += len(line) + 1

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.current_buffer: return
            
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            action = ActionFactory.create_lsp_completion_request(
                file_id=self.current_buffer.file_id,
                offset=self.cursor_offset
            )
            # ИСПОЛЬЗУЕМ ПУБЛИЧНЫЙ API
            self.ipc_client.send_action_async(action)
            return
            
        text = event.text()
        if text and not event.isAutoRepeat():
            action = ActionFactory.create_text_insert(
                file_id=self.current_buffer.file_id,
                offset=self.cursor_offset,
                text=text
            )
            # ИСПОЛЬЗУЕМ ПУБЛИЧНЫЙ API
            self.ipc_client.send_action_async(action)
            
            self.cursor_offset += len(text)
            self.update()
        elif event.key() == Qt.Key.Key_Backspace and not event.isAutoRepeat():
            if self.cursor_offset > 0:
                self.cursor_offset -= 1
                self.update()
        else:
            super().keyPressEvent(event)

    def _blink_cursor(self) -> None:
        self.cursor_visible = not self.cursor_visible
        self.update()