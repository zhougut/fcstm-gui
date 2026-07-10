"""
可拖拽的TreeWidget组件
支持同级项目的拖拽重排序功能
"""

from typing import Optional
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt, QPoint, QMimeData, pyqtSignal
from PyQt5.QtGui import QDrag


class DraggableTreeWidget(QtWidgets.QTreeWidget):
    """支持同级拖拽的QTreeWidget"""
    
    # 当项目重新排序时发出的信号
    itemReordered = pyqtSignal(QtWidgets.QTreeWidgetItem, QtWidgets.QTreeWidgetItem)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drag_start_position = QPoint()
        self.main_window = parent
        
        # 启用拖拽功能
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 处理拖拽开始"""
        if not (event.buttons() & Qt.LeftButton):
            return
            
        # 检查是否达到拖拽距离阈值
        if ((event.pos() - self.drag_start_position).manhattanLength() < 
            QtWidgets.QApplication.startDragDistance()):
            return
            
        # 获取被拖拽的项目
        item = self.itemAt(self.drag_start_position)
        if item is None:
            return
            
        # 检查是否允许拖拽（只允许同级拖拽）
        if not self._can_drag_item(item):
            return
            
        # 开始拖拽
        self._start_drag(item)
        
    def _can_drag_item(self, item):
        """检查项目是否可以拖拽"""
        parent_item = item.parent()
        
        if parent_item is None:
            # 顶级项目 - 检查是否有多个同级项目
            siblings_count = self.topLevelItemCount()
        else:
            # 子项目 - 检查是否有多个同级项目
            siblings_count = parent_item.childCount()
            
        return siblings_count > 1
        
    def _start_drag(self, item):
        """开始拖拽操作"""
        drag = QDrag(self)
        mime_data = QMimeData()
        
        # 设置拖拽数据
        mime_data.setText(item.text(0))
        drag.setMimeData(mime_data)
        
        # 执行拖拽
        drop_action = drag.exec_(Qt.MoveAction)
        
    def dropEvent(self, event):
        """处理拖拽放置事件"""
        if event.source() != self:
            event.ignore()
            return
            
        # 获取拖拽的目标位置
        target_item = self.itemAt(event.pos())
        if target_item is None:
            event.ignore()
            return
            
        # 获取当前选中的项目（被拖拽的项目）
        dragged_item = self.currentItem()
        if dragged_item is None or dragged_item == target_item:
            event.ignore()
            return
            
        # 检查是否为同级拖拽
        if not self._is_same_level(dragged_item, target_item):
            event.ignore()
            return
            
        # 执行同级重排序
        self._reorder_siblings(dragged_item, target_item, event.pos())
        
        # 发出重排序信号
        self.itemReordered.emit(dragged_item, target_item)
        
        event.accept()
        
    def _is_same_level(self, item1, item2):
        """检查两个项目是否在同一级别"""
        return item1.parent() == item2.parent()
        
    def _reorder_siblings(self, dragged_item, target_item, drop_position):
        """重新排序同级项目"""
        parent_item = dragged_item.parent()
        
        if parent_item is None:
            # 顶级项目重排序
            self._reorder_top_level_items(dragged_item, target_item, drop_position)
        else:
            # 子项目重排序
            self._reorder_child_items(parent_item, dragged_item, target_item, drop_position)
                
        # 选中被拖拽的项目
        self.setCurrentItem(dragged_item)
        
    def _reorder_top_level_items(self, dragged_item, target_item, drop_position):
        """重新排序顶级项目"""
        dragged_index = self.indexOfTopLevelItem(dragged_item)
        target_index = self.indexOfTopLevelItem(target_item)
        
        # 移除被拖拽的项目
        dragged_item = self.takeTopLevelItem(dragged_index)
        
        # 计算新的插入位置
        insert_index = self._calculate_insert_index(target_item, target_index, drop_position)
        
        # 插入到新位置
        self.insertTopLevelItem(insert_index, dragged_item)
        
    def _reorder_child_items(self, parent_item, dragged_item, target_item, drop_position):
        """重新排序子项目"""
        dragged_index = parent_item.indexOfChild(dragged_item)
        target_index = parent_item.indexOfChild(target_item)
        
        # 移除被拖拽的项目
        dragged_item = parent_item.takeChild(dragged_index)
        
        # 计算新的插入位置
        insert_index = self._calculate_insert_index(target_item, target_index, drop_position)
        
        # 插入到新位置
        parent_item.insertChild(insert_index, dragged_item)
        
    def _calculate_insert_index(self, target_item, target_index, drop_position):
        """计算插入位置"""
        target_rect = self.visualItemRect(target_item)
        
        if drop_position.y() < target_rect.center().y():
            # 插入到目标项目之前
            return target_index
        else:
            # 插入到目标项目之后
            return target_index + 1
            
    def get_item_order(self, parent_item=None):
        """获取项目的当前顺序"""
        items_order = []
        
        if parent_item is None:
            # 获取顶级项目顺序
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                items_order.append(item.text(0))
        else:
            # 获取子项目顺序
            for i in range(parent_item.childCount()):
                item = parent_item.child(i)
                items_order.append(item.text(0))
                
        return items_order
        
    def copy_from_tree_widget(self, source_tree):
        """从另一个TreeWidget复制所有内容"""
        # 清空当前内容
        self.clear()
        
        # 复制列数
        self.setColumnCount(source_tree.columnCount())
        
        # 复制所有顶级项目
        for i in range(source_tree.topLevelItemCount()):
            source_item = source_tree.topLevelItem(i)
            new_item = self._copy_tree_item_recursive(source_item)
            self.addTopLevelItem(new_item)
            
        # 复制其他属性
        self.setFont(source_tree.font())
        if source_tree.header().isHidden():
            self.header().hide()
        self.setTextElideMode(source_tree.textElideMode())
        self.setHorizontalScrollBarPolicy(source_tree.horizontalScrollBarPolicy())
        self.setAutoScroll(source_tree.autoScroll())
        
    def _copy_tree_item_recursive(self, source_item):
        """递归复制TreeWidget项目"""
        new_item = QtWidgets.QTreeWidgetItem()
        
        # 复制文本和数据
        for column in range(source_item.columnCount()):
            new_item.setText(column, source_item.text(column))
            
        # 复制用户数据
        user_data = source_item.data(0, Qt.UserRole)
        if user_data is not None:
            new_item.setData(0, Qt.UserRole, user_data)
        
        # 递归复制子项目
        for i in range(source_item.childCount()):
            child_item = source_item.child(i)
            new_child = self._copy_tree_item_recursive(child_item)
            new_item.addChild(new_child)
            
        return new_item
