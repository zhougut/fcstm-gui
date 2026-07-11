from PyQt5.QtWidgets import QDialog, QFileDialog, QGraphicsScene, QGraphicsPixmapItem, QGraphicsView, QVBoxLayout
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QPainter
import os
import tempfile

from app.utils.show_state_graph import ShowStateGraph
from app.ui import UIDialogShowGraph
from ..model import StateManager

class CustomGraphicsView(QGraphicsView):

    def wheelEvent(self, event):
        # 计算缩放因子
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor

        # 保存当前场景位置
        old_pos = self.mapToScene(event.pos())

        # 缩放
        if event.angleDelta().y() > 0:
            factor = zoom_in_factor
        else:
            factor = zoom_out_factor
        self.scale(factor, factor)

        # 调整场景位置
        new_pos = self.mapToScene(event.pos())
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

class DialogShowGraph(QDialog, UIDialogShowGraph):
    def __init__(self, parent, state_manager: StateManager, model=None):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.state_manager = state_manager
        self.model = model
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.temp_png_path = os.path.join(tempfile.gettempdir(), 'temp_state_graph.png')
        
        # 创建自定义的CustomGraphicsView并添加到widget容器中
        self.graphics_view_show_graph = CustomGraphicsView()
        layout = QVBoxLayout(self.widget_graph_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.graphics_view_show_graph)
        
        # 连接信号和槽
        self.button_export_graph.clicked.connect(self.export_graph)
        
        # 设置图形视图的属性
        self.graphics_view_show_graph.setDragMode(QGraphicsView.ScrollHandDrag)
        self.graphics_view_show_graph.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view_show_graph.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.graphics_view_show_graph.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.graphics_view_show_graph.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.graphics_view_show_graph.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        
        # 显示状态机图
        self.show_state_graph()
        
    def show_state_graph(self):
        """显示状态机图"""
        # 生成状态机图
        ShowStateGraph.show_state_graph(
            self.state_manager, self.temp_png_path, model=self.model
        )
        
        # 创建场景并显示图像
        scene = QGraphicsScene()
        pixmap = QPixmap(self.temp_png_path)
        
        # 增加图片大小
        scaled_pixmap = pixmap.scaled(pixmap.width() * 2, pixmap.height() * 2, 
                                    Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        item = QGraphicsPixmapItem(scaled_pixmap)
        scene.addItem(item)
        
        # 设置场景到视图
        self.graphics_view_show_graph.setScene(scene)
        self.graphics_view_show_graph.setRenderHint(QPainter.Antialiasing)
        self.graphics_view_show_graph.setRenderHint(QPainter.SmoothPixmapTransform)
        self.graphics_view_show_graph.setRenderHint(QPainter.TextAntialiasing)
        
        # 调整视图以适应内容
        self.graphics_view_show_graph.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
        
    def export_graph(self):
        """导出状态机图"""
        # 获取保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出状态机图",
            "./",
            "PNG Files (*.png);;All Files (*)"
        )
        
        if file_path:
            # 复制临时文件到目标位置
            if os.path.exists(self.temp_png_path):
                import shutil
                shutil.copy2(self.temp_png_path, file_path)
    
    def closeEvent(self, event):
        """关闭对话框时清理临时文件"""
        if os.path.exists(self.temp_png_path):
            try:
                os.remove(self.temp_png_path)
            except Exception as e:
                pass
        super().closeEvent(event)
