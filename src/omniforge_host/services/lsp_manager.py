# src/omniforge_host/services/lsp_manager.py
# Обновлены импорты и создание Action
from __future__ import annotations

import asyncio
import os
from omniforge_host.state.store import Store
from omniforge_host.services.lsp_client import LspClient
from omniforge_api.actions import Action, ActionType, LspCompletionRequestAction, LspCompletionResponseAction, LspDiagnosticsAction, LspInitializedAction
from omniforge_api.ipc_action_handler import ActionHandler
from omniforge_api.models import AppState, EditorBuffer
from omniforge_api.logger import get_logger
from omniforge_api.models import AppState, EditorState, EditorBuffer

class LspManager(ActionHandler):
    def __init__(self, store: Store) -> None:
        self._store = store
        self._log = get_logger("lsp_manager")
        self._client: LspClient | None = None
        self._initialized = False
        self._synced_versions: dict[str, int] = {}
        self._store.subscribe(self._on_state_changed)

    async def handle(self, action: Action) -> None:
        if isinstance(action, LspCompletionRequestAction):
            await self.request_completions(action.file_id, action.offset)

    async def _on_state_changed(self, state: AppState, changed_keys: set[str]) -> None:
        if "project" in changed_keys and state.project.is_loaded and not self._initialized:
            await self._start_lsp(state.project.root_path)
            
        if "editor" in changed_keys:
            await self._sync_text_changes(state.editor)

    async def _start_lsp(self, root_path: str | None) -> None:
        if not root_path: return
        self._log.info("Starting pylsp for project", path=root_path)
        self._client = LspClient(command=["pylsp"], root_path=root_path)
        self._client.on_notification("textDocument/publishDiagnostics", self._on_diagnostics)
        
        try:
            await self._client.start()
            self._initialized = True
            await self._store.dispatch(LspInitializedAction())
        except Exception as e:
            self._log.error("Failed to start LSP", exc_info=e)

    async def _sync_text_changes(self, editor: EditorState) -> None:
        if not self._client: return
            
        for file_id, buffer in editor.open_buffers.items():
            if buffer.version == 1 and file_id not in self._synced_versions:
                await self._client.send_notification("textDocument/didOpen", {
                    "textDocument": {
                        "uri": self._client._path_to_uri(buffer.file_path),
                        "languageId": "python",
                        "version": buffer.version,
                        "text": buffer.content
                    }
                })
                self._synced_versions[file_id] = buffer.version
                
            elif buffer.version > self._synced_versions.get(file_id, 0):
                await self._client.send_notification("textDocument/didChange", {
                    "textDocument": {
                        "uri": self._client._path_to_uri(buffer.file_path),
                        "version": buffer.version
                    },
                    "contentChanges": [{"text": buffer.content}]
                })
                self._synced_versions[file_id] = buffer.version

    async def request_completions(self, file_id: str, offset: int) -> None:
        if not self._client: return
        buffer = self._store.state.editor.open_buffers.get(file_id)
        if not buffer: return
            
        line, char = self._offset_to_position(buffer.content, offset)
        
        result = await self._client.send_request("textDocument/completion", {
            "textDocument": {"uri": self._client._path_to_uri(buffer.file_path)},
            "position": {"line": line, "character": char}
        })
        
        items = []
        if isinstance(result, dict) and "items" in result:
            for item in result["items"][:50]: items.append({"label": item.get("label", ""), "detail": item.get("detail", "")})
        elif isinstance(result, list):
             for item in result[:50]: items.append({"label": item.get("label", ""), "detail": item.get("detail", "")})
                
        action = LspCompletionResponseAction(file_id=file_id, offset=offset, items=items)
        await self._store.dispatch(action)

    async def _on_diagnostics(self, params: dict) -> None:
        uri = params.get("uri", "")
        file_path = LspClient.uri_to_path(uri)
        file_id = os.path.basename(file_path)
        
        raw_diags = params.get("diagnostics", [])
        diags_payload = []
        
        for d in raw_diags:
            diags_payload.append({
                "message": d.get("message", "Unknown error"),
                "severity": d.get("severity", 1), 
                "start_offset": 0,
                "end_offset": 0
            })
            
        action = LspDiagnosticsAction(file_id=file_id, diagnostics=diags_payload)
        await self._store.dispatch(action)

    @staticmethod
    def _offset_to_position(text: str, offset: int) -> tuple[int, int]:
        line = 0
        char = 0
        current_offset = 0
        for l in text.split('\n'):
            line_len = len(l)
            if current_offset + line_len >= offset:
                char = offset - current_offset
                return line, char
            current_offset += line_len + 1
            line += 1
        return line, char