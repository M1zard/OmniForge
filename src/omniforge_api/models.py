# src/omniforge_api/models.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from omniforge_api.types import SessionId, Timestamp
from enum import IntEnum, StrEnum

class FileNodeType(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"

class FileNode(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    path: str
    node_type: FileNodeType
    children: dict[str, FileNode] = Field(default_factory=dict)
    
    def add_child(self, child: FileNode) -> FileNode:
        new_children = {**self.children, child.name: child}
        return self.model_copy(update={"children": new_children})

class ProjectState(BaseModel):
    model_config = ConfigDict(frozen=True)
    root_path: str | None = None
    is_loaded: bool = False
    tree: FileNode | None = None

class EditorBuffer(BaseModel):
    model_config = ConfigDict(frozen=True)
    file_id: str
    file_path: str
    content: str = ""
    version: int = 0
    is_dirty: bool = False

class EditorState(BaseModel):
    model_config = ConfigDict(frozen=True)
    active_file_id: str | None = None
    open_buffers: dict[str, EditorBuffer] = Field(default_factory=dict)

class DiagnosticSeverity(IntEnum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4

class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)
    message: str
    start_offset: int
    end_offset: int
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR

class CompletionItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    label: str
    detail: str = ""

class LspState(BaseModel):
    model_config = ConfigDict(frozen=True)
    is_initialized: bool = False
    diagnostics: dict[str, list[Diagnostic]] = Field(default_factory=dict) 
    completions: list[CompletionItem] = Field(default_factory=list)
    active_completion_offset: int = -1

# --- TERMINAL STATE (НОВОЕ) ---
class TermSessionStatus(StrEnum):
    CONNECTING = "connecting"
    RUNNING = "running"
    EXITED = "exited"

class TermSession(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    pid: int | None = None
    shell: str = ""
    cwd: str = ""
    status: TermSessionStatus = TermSessionStatus.CONNECTING
    exit_code: int | None = None

class TerminalState(BaseModel):
    model_config = ConfigDict(frozen=True)
    sessions: dict[str, TermSession] = Field(default_factory=dict)
    active_session_id: str | None = None

class AppState(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: SessionId | None = None
    editor: EditorState = EditorState()
    project: ProjectState = ProjectState()
    lsp: LspState = LspState()
    terminal: TerminalState = TerminalState() # Добавлено
    last_updated: Timestamp = Timestamp(0.0)