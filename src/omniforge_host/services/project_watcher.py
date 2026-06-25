# src/omniforge_host/services/project_watcher.py
from __future__ import annotations

import asyncio
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from omniforge_host.state.store import Store
# Импортируем конкретный экшен, который ожидает наш реड्यूсер
from omniforge_api.actions import ActionFactory, ProjectTreeInitializedAction 
from omniforge_host.state.state_types import FileNode, FileNodeType, ProjectState, AppState
from omniforge_api.logger import get_logger

class FSWatcherHandler(FileSystemEventHandler):
    """Перехватывает события ФС и диспетчеризирует их в Store."""
    def __init__(self, store: Store, loop: asyncio.AbstractEventLoop) -> None:
        self._store = store
        self._loop = loop
        self._log = get_logger("fs_watcher")

    def dispatch(self, event: FileSystemEvent) -> None:
        # Watchdog работает в своем потоке. Переводим выполнение в asyncio цикл Host корректно
        if event.is_directory:
            return # Пока обрабатываем только файлы для упрощения
            
        src_path = event.src_path
        name = os.path.basename(src_path)
        
        if event.event_type == "created":
            asyncio.run_coroutine_threadsafe(
                self._store.dispatch(ActionFactory.create_file_created(src_path, name, False)),
                self._loop
            )
        elif event.event_type == "deleted":
            asyncio.run_coroutine_threadsafe(
                self._store.dispatch(ActionFactory.create_file_deleted(src_path, name)),
                self._loop
            )

class ProjectService:
    """Управление логикой проектного дерева."""
    def __init__(self, store: Store) -> None:
        self._store = store
        self._observer: Observer | None = None
        self._log = get_logger("project_service")
        self._store.subscribe(self._on_state_changed)

    async def _on_state_changed(self, state: AppState, changed_keys: set[str]) -> None:
        if "project" in changed_keys and state.project.is_loaded and not self._observer:
            await self._start_watching(state.project.root_path)
            
            # === РЕШЕНИЕ DEADLOCK: Запускаем сканирование как фоновую задачу ===
            # Это освобождает lock в Store и позволяет обработать экшен дерева
            asyncio.create_task(self._initial_scan(state.project.root_path))

    async def _start_watching(self, root_path: str | None) -> None:
        if not root_path:
            return
            
        loop = asyncio.get_running_loop()
        handler = FSWatcherHandler(self._store, loop)
        self._observer = Observer()
        self._observer.schedule(handler, root_path, recursive=True)
        self._observer.start()
        self._log.info("fs_watcher_started", path=root_path)

    async def _initial_scan(self, root_path: str | None) -> None:
        """Простое сканирование директории для построения дерева."""
        try:
            if not root_path or not os.path.exists(root_path):
                print(f"[SCANNER CRITICAL] Путь не существует или пуст: {root_path}")
                return
                
            print(f"[SCANNER INFO] Начинаем сканирование папки: {root_path}")
            root_node = await self._build_tree_recursive_v2(root_path)
            
            if root_node:
                print(f"[SCANNER INFO] Сканирование завершено успешно! Корневая нода: {root_node.name}")
                
                # Конвертируем готовую и валидную ноду в словарь, так как экшен требует dict!
                tree_dict = root_node.model_dump(mode='python')
                print(f"[SCANNER INFO] Успешно перевели дерево в dict. Элементов в корне: {len(tree_dict.get('children', {}))}")
                
                # Передаем словарь в экшен!
                action = ProjectTreeInitializedAction(tree=tree_dict)
                
                print(f"[SCANNER INFO] Отправляем экшен в Store...")
                await self._store.dispatch(action)
                print(f"[SCANNER INFO] Экшен успешно обработан Store!")
            else:
                print("[SCANNER CRITICAL] Сканер вернул None!")
                
        except Exception as general_error:
            print(f"\n[!!! CRITICAL PROJECT SERVICE ERROR !!!]")
            import traceback
            traceback.print_exc()
            print(f"=========================================\n")

    async def _build_tree_recursive_v2(self, current_path: str) -> FileNode | None:
        """Рекурсивное создание дерева снизу вверх через словарь для Pydantic."""
        name = os.path.basename(current_path)
        if not name and current_path.endswith(os.sep):
            name = current_path
            
        if not os.path.isdir(current_path):
            return FileNode(name=name, path=current_path, node_type=FileNodeType.FILE, children={})
            
        try:
            entries = os.listdir(current_path)
        except PermissionError:
            return FileNode(name=name, path=current_path, node_type=FileNodeType.DIRECTORY, children={})
            
        # ТЕПЕРЬ ЭТО СЛОВАРЬ dict[str, FileNode], как требует Pydantic!
        child_nodes: dict[str, FileNode] = {}
        
        for entry in entries:
            # Игнорируем мусорные папки
            if entry in (".venv", "env", ".git", "__pycache__", ".idea", ".vscode"):
                continue
                
            full_path = os.path.join(current_path, entry)
            if os.path.isdir(full_path):
                child_dir = await self._build_tree_recursive_v2(full_path)
                if child_dir:
                    child_nodes[entry] = child_dir  # Сохраняем по ключу (имени файла/папки)
            else:
                child_nodes[entry] = FileNode(
                    name=entry, 
                    path=full_path, 
                    node_type=FileNodeType.FILE, 
                    children={}
                )
                
        # Создаем ноду директории, передавая словарь детей
        return FileNode(
            name=name,
            path=current_path,
            node_type=FileNodeType.DIRECTORY,
            children=child_nodes
        )

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()