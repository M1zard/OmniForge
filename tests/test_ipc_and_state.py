# tests/test_ipc_and_state.py
import pytest
from omniforge_api.actions import TextInsertAction, ActionFactory, Action
from omniforge_api.ipc_protocol import IPCProtocol, StateDelta, ActionAdapter
from omniforge_api.models import AppState, EditorState, DiagnosticSeverity, Diagnostic
from pydantic import TypeAdapter
from typing import get_type_hints

def test_action_serialization_roundtrip():
    action = ActionFactory.create_text_insert("file1", 10, "hello")
    action_dict = action.model_dump(mode='python')
    
    # Эмулируем IPC
    encoded = IPCProtocol.encode(1, "action", "session1", action_dict)
    _, decoded_dict = IPCProtocol.decode(encoded)
    
    # Десериализация Discriminated Union
    parsed_action = ActionAdapter.validate_python(decoded_dict)
    
    assert isinstance(parsed_action, TextInsertAction)
    assert parsed_action.file_id == "file1"
    assert parsed_action.offset == 10

def test_delta_reconstruction_pydantic_v2():
    # Симуляция Delta Update от Host
    delta_data = {
        "changed_keys": ["editor"],
        "patches": {
            "editor": {
                "active_file_id": "main.py",
                "open_buffers": {}
            }
        }
    }
    delta = StateDelta.model_validate(delta_data)
    
    current_state = AppState()
    update_dict = {}
    type_hints = get_type_hints(AppState)
    
    for key in delta.changed_keys:
        if key in type_hints and key in delta.patches:
            field_type = type_hints[key]
            adapter = TypeAdapter(field_type)
            update_dict[key] = adapter.validate_python(delta.patches[key])
            
    new_state = current_state.model_copy(update=update_dict)
    assert new_state.editor.active_file_id == "main.py"

def test_lsp_severity_int_enum():
    # Проверяем, что int от LSP корректно мапится в IntEnum
    diag = Diagnostic(message="test", start_offset=0, end_offset=1, severity=2)
    assert diag.severity == DiagnosticSeverity.WARNING
    assert isinstance(diag.severity, int) # IntEnum наследуется от int