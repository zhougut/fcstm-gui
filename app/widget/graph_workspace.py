"""State graph workbench view."""

from __future__ import unicode_literals

from PyQt5 import QtCore, QtGui, QtWidgets


class GraphView(QtWidgets.QGraphicsView):
    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)


class GraphWorkspace(QtWidgets.QWidget):
    refresh_requested = QtCore.pyqtSignal()
    export_requested = QtCore.pyqtSignal(str)
    cancel_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("graph_panel")
        self._available = False
        self._busy = False
        self._build_ui()
        self._update_actions()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(8)
        self.refresh_button = self._button("刷新", "graph_refresh_button")
        self.fit_button = self._button("适应", "graph_fit_button")
        self.actual_button = self._button("100%", "graph_actual_button")
        self.reset_button = self._button("重置", "graph_reset_button")
        self.export_combo = QtWidgets.QComboBox(self)
        self.export_combo.setObjectName("graph_export_combo")
        self.export_combo.addItems(["plantuml", "png", "svg", "pdf"])
        self.export_combo.setFixedWidth(100)
        self.export_combo.setMinimumContentsLength(8)
        self.export_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.export_button = self._button("导出", "graph_export_button")
        self.cancel_button = self._button("停止", "graph_cancel_button")
        for widget in (
            self.refresh_button,
            self.fit_button,
            self.actual_button,
            self.reset_button,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)
        controls.addWidget(self.export_combo)
        controls.addWidget(self.export_button)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        self.status_label = QtWidgets.QLabel("当前版本无有效快照", self)
        self.status_label.setObjectName("graph_status_label")
        layout.addWidget(self.status_label)
        self.view = GraphView(self)
        self.view.setObjectName("graph_view")
        self.view.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.view.setRenderHints(
            QtGui.QPainter.Antialiasing
            | QtGui.QPainter.SmoothPixmapTransform
            | QtGui.QPainter.TextAntialiasing
        )
        layout.addWidget(self.view, 1)
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.fit_button.clicked.connect(self.fit_graph)
        self.actual_button.clicked.connect(self.actual_size)
        self.reset_button.clicked.connect(self.reset_view)
        self.export_button.clicked.connect(
            lambda: self.export_requested.emit(self.export_combo.currentText())
        )
        self.cancel_button.clicked.connect(self.cancel_requested)

    def _button(self, text, name):
        button = QtWidgets.QPushButton(text, self)
        button.setObjectName(name)
        button.setFixedWidth(64)
        button.setAccessibleName(text)
        button.setToolTip(text)
        return button

    def set_available(self, available, revision=None, selected_path=None):
        self._available = bool(available)
        if available:
            suffix = " | 选择 {}".format(selected_path) if selected_path else ""
            self.status_label.setText("版本 {}{}".format(revision, suffix))
        else:
            self.status_label.setText("当前版本无有效快照")
            self.view.setScene(None)
        self._update_actions()

    def set_selection(self, selected_path):
        if self._available:
            text = self.status_label.text().split(" | 选择", 1)[0]
            self.status_label.setText(
                text + (" | 选择 " + selected_path if selected_path else "")
            )

    def set_busy(self, busy, status=None):
        self._busy = bool(busy)
        if status:
            self.status_label.setText(status)
        self._update_actions()

    def present_png(self, data, revision):
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(data, "PNG") or pixmap.isNull():
            self.show_error("状态图 PNG 无法加载")
            return
        scene = QtWidgets.QGraphicsScene(self)
        scene.addPixmap(pixmap)
        self.view.setScene(scene)
        self._busy = False
        self.status_label.setText("版本 {} | 就绪".format(revision))
        self.fit_graph()
        self._update_actions()

    def fit_graph(self):
        scene = self.view.scene()
        if scene is not None and not scene.sceneRect().isEmpty():
            self.view.fitInView(scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def actual_size(self):
        self.view.resetTransform()

    def reset_view(self):
        self.view.resetTransform()
        self.fit_graph()

    def show_error(self, message):
        self._busy = False
        self.status_label.setText("失败：" + str(message))
        self.status_label.setToolTip(str(message))
        self._update_actions()

    def show_stale(self, message):
        self._busy = False
        self.status_label.setText("已失效：" + str(message))
        self.status_label.setToolTip(str(message))
        self._update_actions()

    def _update_actions(self):
        ready = self._available and not self._busy
        self.refresh_button.setEnabled(ready)
        self.fit_button.setEnabled(ready and self.view.scene() is not None)
        self.actual_button.setEnabled(ready and self.view.scene() is not None)
        self.reset_button.setEnabled(ready and self.view.scene() is not None)
        self.export_combo.setEnabled(ready)
        self.export_button.setEnabled(ready)
        self.cancel_button.setEnabled(self._busy)
