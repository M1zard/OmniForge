# src/omniforge_api/actions.py
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Union, Literal
from pydantic import BaseModel, ConfigDict, Field
from omniforge_api.types import ActionId, generate_action_id, Timestamp
import time

class ActionType(StrEnum):
    # System
    INIT_SESSION = "system.init_session"
    
    # Editor
    TEXT_INSERT = "editor.text_insert"
    
    # Project
    PROJECT_OPEN = "project.open"
    PROJECT_TREE_INITIALIZED = "project.tree_initialized"
    
    # LSP
    LSP_INITIALIZED = "lsp.initialized"
    LSP_DIAGNOSTICS_PUBLISHED = "lsp.diagnostics_published"
    LSP_COMPLETION_REQUEST = "lsp.completion_request"
    LSP_COMPLETION_RESPONSE = "lsp.completion_response"

    # Terminal (НОВОЕ)
    TERM_CREATE = "term.create"
    TERM_CLOSE = "term.close"
    TERM_RESIZE = "term.resize"
    TERM_EXITED = "term.exited"

class BaseAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action_id: ActionId = Field(default_factory=generate_action_id)
    timestamp: Timestamp = Field(default_factory=lambda: Timestamp(time.time()))

# --- System ---
class InitSessionAction(BaseAction):
    action_type: Literal[ActionType.INIT_SESSION] = ActionType.INIT_SESSION
    session_id: str

# --- Editor ---
class TextInsertAction(BaseAction):
    action_type: Literal[ActionType.TEXT_INSERT] = ActionType.TEXT_INSERT
    file_id: str
    offset: int
    text: str

# --- Project ---
class ProjectOpenAction(BaseAction):
    action_type: Literal[ActionType.PROJECT_OPEN] = ActionType.PROJECT_OPEN
    root_path: str

class ProjectTreeInitializedAction(BaseAction):
    action_type: Literal[ActionType.PROJECT_TREE_INITIALIZED] = ActionType.PROJECT_TREE_INITIALIZED
    tree: dict

# --- LSP ---
class LspInitializedAction(BaseAction):
    action_type: Literal[ActionType.LSP_INITIALIZED] = ActionType.LSP_INITIALIZED

class LspDiagnosticsAction(BaseAction):
    action_type: Literal[ActionType.LSP_DIAGNOSTICS_PUBLISHED] = ActionType.LSP_DIAGNOSTICS_PUBLISHED
    file_id: str
    diagnostics: list[dict[str, object]]

class LspCompletionRequestAction(BaseAction):
    action_type: Literal[ActionType.LSP_COMPLETION_REQUEST] = ActionType.LSP_COMPLETION_REQUEST
    file_id: str
    offset: int

class LspCompletionResponseAction(BaseAction):
    action_type: Literal[ActionType.LSP_COMPLETION_RESPONSE] = ActionType.LSP_COMPLETION_RESPONSE
    file_id: str
    offset: int
    items: list[dict[str, str]]

# --- Terminal (НОВОЕ) ---
class TermCreateAction(BaseAction):
    action_type: Literal[ActionType.TERM_CREATE] = ActionType.TERM_CREATE
    session_id: str # Генерируется на клиенте для немедленного подписывания на топик
    shell: str | None = None
    cwd: str | None = None

class TermCloseAction(BaseAction):
    action_type: Literal[ActionType.TERM_CLOSE] = ActionType.TERM_CLOSE
    session_id: str

class TermResizeAction(BaseAction):
    action_type: Literal[ActionType.TERM_RESIZE] = ActionType.TERM_RESIZE
    session_id: str
    rows: int
    cols: int

class TermStatusUpdateAction(BaseAction):
    action_type: Literal["term.status_update"] = "term.status_update"
    session_id: str
    pid: int

class TermExitedAction(BaseAction):
    action_type: Literal[ActionType.TERM_EXITED] = ActionType.TERM_EXITED
    session_id: str
    exit_code: int

Action = Annotated[
    Union[
        InitSessionAction,
        TextInsertAction,
        ProjectOpenAction,
        ProjectTreeInitializedAction,
        LspInitializedAction,
        LspDiagnosticsAction,
        LspCompletionRequestAction,
        LspCompletionResponseAction,
        TermCreateAction,
        TermStatusUpdateAction,
        TermCloseAction,
        TermResizeAction,
        TermExitedAction
    ],
    Field(discriminator='action_type')
]

class ActionFactory:
    @staticmethod
    def create_text_insert(file_id: str, offset: int, text: str) -> TextInsertAction:
        return TextInsertAction(file_id=file_id, offset=offset, text=text)
    
    @staticmethod
    def create_project_open(root_path: str) -> ProjectOpenAction:
        return ProjectOpenAction(root_path=root_path)

    @staticmethod
    def create_lsp_completion_request(file_id: str, offset: int) -> LspCompletionRequestAction:
        return LspCompletionRequestAction(file_id=file_id, offset=offset)

    @staticmethod
    def create_term_create(session_id: str, cwd: str | None = None) -> TermCreateAction:
        return TermCreateAction(session_id=session_id, cwd=cwd)

    @staticmethod
    def create_term_close(session_id: str) -> TermCloseAction:
        return TermCloseAction(session_id=session_id)

    @staticmethod
    def create_term_resize(session_id: str, rows: int, cols: int) -> TermResizeAction:
        return TermResizeAction(session_id=session_id, rows=rows, cols=cols)
    @staticmethod
    def create_term_status_update(session_id: str, pid: int) -> TermStatusUpdateAction:
        return TermStatusUpdateAction(session_id=session_id, pid=pid)