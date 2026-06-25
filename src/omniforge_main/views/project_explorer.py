# src/omniforge_main/views/project_explorer.py
from __future__ import annotations

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from omniforge_host.state.state_types import FileNode, FileNodeType

class ProjectExplorer(QWidget):
    """Панель навигации по проекту. Подписывается на ProjectState."""
    def __init__(self) -> None:
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.header = QLabel("Project Explorer")
        self.header.setStyleSheet("font-weight: bold; padding: 5px; background-color: #2d2d2d; color: #cccccc;")
        self.layout.addWidget(self.header)
        
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        self.layout.addWidget(self.tree_widget)

    def update_tree(self, tree: FileNode | None) -> None:
        """Полная перерисовка дерева. В V2 будет инкрементальной."""
        self.tree_widget.clear()
        if not tree:
            return
            
        self._add_node(self.tree_widget.invisibleRootItem(), tree)
        self.tree_widget.expandAll()

    def _add_node(self, parent: QTreeWidgetItem | QTreeWidget, node: FileNode) -> None:
        item = QTreeWidgetItem(parent, [node.name])
        item.setData(0, Qt.ItemDataRole.UserRole, node.path)
        
        # Исправляем имена StandardPixmap для PySide6
        if node.node_type == FileNodeType.DIRECTORY:
            item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon))
            # Рекурсивно добавляем детей
            if node.children:
                for child_node in node.children.values():
                    self._add_node(item, child_node)
        else:
            item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon))