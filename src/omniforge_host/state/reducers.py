from __future__ import annotations

import time
from omniforge_api.actions import (
    Action, TextInsertAction, ProjectOpenAction, ProjectTreeInitializedAction, 
    LspDiagnosticsAction, LspCompletionResponseAction, LspInitializedAction,
    TermCreateAction, TermCloseAction, TermResizeAction, TermExitedAction, 
    TermStatusUpdateAction, InitSessionAction
)
from omniforge_api.models import (
    AppState, EditorState, ProjectState, LspState, TerminalState, 
    FileNode, EditorBuffer, Diagnostic, DiagnosticSeverity, CompletionItem,
    TermSession, TermSessionStatus
)

def editor_reducer(state: EditorState, action: Action) -> EditorState:
    match action:
        case TextInsertAction(file_id=file_id, offset=offset, text=text):
            if file_id not in state.open_buffers:
                new_buffer = EditorBuffer(file_id=file_id, file_path=file_id, content="")
                new_buffers = {**state.open_buffers, file_id: new_buffer}
                state = state.model_copy(update={"open_buffers": new_buffers, "active_file_id": file_id})

            old_buffer = state.open_buffers[file_id]
            current_content = old_buffer.content
            new_content = current_content[:offset] + text + current_content[offset:]
            
            new_buffer = old_buffer.model_copy(update={
                "content": new_content,
                "version": old_buffer.version + 1,
                "is_dirty": True
            })
            
            final_buffers = {**state.open_buffers, file_id: new_buffer}
            return state.model_copy(update={"open_buffers": final_buffers})
        case _:
            return state

def project_reducer(state: ProjectState, action: Action) -> ProjectState:
    match action:
        case ProjectOpenAction(root_path=root_path):
            return state.model_copy(update={"root_path": root_path, "is_loaded": True})
        case ProjectTreeInitializedAction(tree=tree_dict):
            tree = FileNode.model_validate(tree_dict)
            return state.model_copy(update={"tree": tree})
        case _:
            return state

def lsp_reducer(state: LspState, action: Action) -> LspState:
    match action:
        case LspInitializedAction():
            return state.model_copy(update={"is_initialized": True})
        case LspDiagnosticsAction(file_id=file_id, diagnostics=raw_diags):
            parsed_diags = [
                Diagnostic(
                    message=d.get("message", ""),
                    start_offset=d.get("start_offset", 0),
                    end_offset=d.get("end_offset", 0),
                    severity=DiagnosticSeverity(d.get("severity", 1))
                ) for d in raw_diags if isinstance(d, dict)
            ]
            new_diagnostics = {**state.diagnostics, file_id: parsed_diags}
            return state.model_copy(update={"diagnostics": new_diagnostics})
        case LspCompletionResponseAction(offset=offset, items=raw_items):
            parsed_items = [
                CompletionItem(label=i.get("label", ""), detail=i.get("detail", "")) 
                for i in raw_items if isinstance(i, dict)
            ]
            return state.model_copy(update={"completions": parsed_items, "active_completion_offset": offset})
        case _:
            return state

def terminal_reducer(state: TerminalState, action: Action) -> TerminalState:
    match action:
        case TermCreateAction(session_id=sid, shell=sh, cwd=cwd):
            if sid in state.sessions: return state
            new_session = TermSession(session_id=sid, shell=sh or "", cwd=cwd or "", status=TermSessionStatus.CONNECTING)
            new_sessions = {**state.sessions, sid: new_session}
            return state.model_copy(update={"sessions": new_sessions, "active_session_id": sid})
            
        case TermStatusUpdateAction(session_id=sid, pid=pid):
            if sid not in state.sessions: return state
            old_session = state.sessions[sid]
            updated_session = old_session.model_copy(update={"status": TermSessionStatus.RUNNING, "pid": pid})
            new_sessions = {**state.sessions, sid: updated_session}
            return state.model_copy(update={"sessions": new_sessions})
            
        case TermExitedAction(session_id=sid, exit_code=ec):
            if sid not in state.sessions: return state
            old_session = state.sessions[sid]
            updated_session = old_session.model_copy(update={"status": TermSessionStatus.EXITED, "exit_code": ec})
            new_sessions = {**state.sessions, sid: updated_session}
            return state.model_copy(update={"sessions": new_sessions})
            
        case TermCloseAction(session_id=sid):
            if sid not in state.sessions: return state
            new_sessions = {k: v for k, v in state.sessions.items() if k != sid}
            new_active = state.active_session_id if sid != state.active_session_id else None
            return state.model_copy(update={"sessions": new_sessions, "active_session_id": new_active})
            
        case _:
            return state

def root_reducer(state: AppState, action: Action) -> AppState:
    new_state = state
    
    match action:
        case InitSessionAction(session_id=sid):
            new_state = new_state.model_copy(update={"session_id": sid})
        case _:
            pass
    
    new_editor = editor_reducer(new_state.editor, action)
    new_project = project_reducer(new_state.project, action)
    new_lsp = lsp_reducer(new_state.lsp, action)
    new_terminal = terminal_reducer(new_state.terminal, action)
    
    if (new_editor is new_state.editor and 
        new_project is new_state.project and 
        new_lsp is new_state.lsp and 
        new_terminal is new_state.terminal and
        new_state is state):
        return state
        
    return new_state.model_copy(update={
        "editor": new_editor,
        "project": new_project,
        "lsp": new_lsp,
        "terminal": new_terminal,
        "last_updated": time.time()
    })