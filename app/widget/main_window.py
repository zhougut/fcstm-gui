from typing import Optional, Dict, List
import os

import PyQt5.Qt
from PyQt5 import QtWidgets, QtGui
from PyQt5.Qt import QMainWindow
from PyQt5.QtCore import Qt, QPoint
import qtawesome as qta
from pyfcstm.model import parse_dsl_node_to_state_machine
from pyfcstm.dsl import parse_with_grammar_entry

from app.ui import UIMainWindow
from app.utils.create_formLayout_dialog import create_formlayout_dialog
from ..model import State, StateManager
from app.utils.dsl_to_ui import dsl_to_state_manager, update_ui_from_state_manager
from app.utils.export_to_word import export_statechart_to_word
from app.utils.export_to_excel import export_statechart_to_excel
from .dialog_edit_state import DialogEditState
from .dialog_show_graph import DialogShowGraph
from app.utils.ui_to_dsl import state_manager_to_dsl

class AppMainWindow(QMainWindow, UIMainWindow):
    state_manager: Optional[StateManager]

    def __init__(self):
        QMainWindow.__init__(self)
        self.setupUi(self)
        self.at_page_initial = True
        #self.fcstm_state_chart = None
        self.code_file_path = "./"
        self.state_machine_file_path = "./"
        self._init()

    def _init(self):
        #初始化窗口格式
        self._init_window_style()
        #初始化导入状态机按钮
        self._init_import_state_chart()
        self._init_tree_all_state_context_menu()
        #初始化文本框变化操作
        self._init_edit_text_change()
        #初始化添加状态按钮
        self._init_button_state_machine_add_state()
        #初始化导出按钮
        self._init_button_state_machine_export()
        #初始化新建状态机按钮
        self._init_button_initial_new_state_machine()
        #初始化验证按钮
        self._init_button_state_machine_validation()
        #初始化图生成按钮
        self._init_button_state_machine_graph_gen()
        #展开所有状态按钮
        self._init_button_state_machine_expand_all()
        #折叠所有状态按钮
        self._init_button_state_machine_fold_all()
        '''
        self._init_button_save_state()
        '''

    def _init_window_style(self):
        self.stackedWidget_state_machine.setCurrentIndex(0)
        self._init_tree_style()
        self._init_button_style()
        self._init_text_edit_style()

    def _init_import_state_chart(self):
        self._init_button_initial_import_state_machine()
        self._init_button_state_machine_import_state()

    def _init_button_initial_import_state_machine(self):
        self.button_initial_import_state_machine.clicked.connect(lambda: self._import_statechart())

    def _init_button_state_machine_import_state(self):
        self.button_import_state_machine.clicked.connect(lambda: self._import_statechart())

    def _init_button_initial_new_state_machine(self):
        self.button_initial_new_state_machine.clicked.connect(lambda: self._new_state_machine())

    def _new_state_machine(self):
        self.state_manager = StateManager()
        if self.at_page_initial:
            self.stackedWidget_state_machine.setCurrentIndex(1)
            self.at_page_initial = False

    def _init_tree_style(self):
        self.tree_all_state.header().hide()
        self.tree_all_state.setTextElideMode(Qt.ElideNone)
        self.tree_all_state.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        #self.tree_all_state.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.tree_all_state.header().setMinimumSectionSize(800)
        self.tree_all_state.setAutoScroll(False)

    def _init_button_style(self):
        button_style = """
            QToolButton {
                border: none;
                background-color: #FFFACD;
                font-size: 20px;
                padding: 50px 16px 8px 16px;  /* 上 右 下 左 的内边距 */
                border-radius: 6px;
                spacing: 5px;  /* 图标和文字之间的间距 */
            }

            QToolButton:hover {
                background-color: #ADD8E6;
            }

            QToolButton:pressed {
                background-color: #ADD8E6;
            }
        """
        self.button_initial_new_state_machine.setMinimumSize(300, 300)
        self.button_initial_import_state_machine.setMinimumSize(300, 300)
        self.button_initial_new_state_machine.setStyleSheet(button_style)
        self.button_initial_import_state_machine.setStyleSheet(button_style)
        
        # 设置按钮图标和文字
        new_icon = qta.icon('fa5s.plus-circle', color='#000000')
        import_icon = qta.icon('fa5s.file-import', color='#000000')
        
        self.button_initial_new_state_machine.setIcon(new_icon)
        self.button_initial_import_state_machine.setIcon(import_icon)
        
        # 设置图标大小
        icon_size = 64
        self.button_initial_new_state_machine.setIconSize(PyQt5.Qt.QSize(icon_size, icon_size))
        self.button_initial_import_state_machine.setIconSize(PyQt5.Qt.QSize(icon_size, icon_size))
        
        # 设置文字在图标下方
        self.button_initial_new_state_machine.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_initial_import_state_machine.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

    def _init_text_edit_style(self):
        # 设置字体为微软雅黑，大小为11号
        font = QtGui.QFont("微软雅黑", 11)
        
        # 配置所有文本编辑框
        for text_edit in [self.edit_lifecycle, self.edit_var_def, self.edit_state_transition]:
            # 设置字体
            text_edit.setFont(font)
            
            # 设置tab为4个空格
            text_edit.setTabStopWidth(
                QtGui.QFontMetrics(font).width(' ') * 4
            )

    def _init_edit_text_change(self):
        # 连接状态转移信息的文本框的内容变化信号，用于自动保存
        self.edit_state_transition.textChanged.connect(self._on_transition_text_changed)
        # 连接状态生命周期信息的文本框的内容变化信号，用于自动保存
        self.edit_lifecycle.textChanged.connect(self._on_lifecycle_text_changed)
        # 连接变量定义文本框的内容变化信号
        self.edit_var_def.textChanged.connect(self._on_var_def_text_changed)

    def _init_tree_all_state_context_menu(self):
        self.tree_all_state.setContextMenuPolicy(Qt.CustomContextMenu)

        self.tree_all_state.customContextMenuRequested.connect(lambda pos: self.show_tree_all_state_context_menu(pos))
        
        # 连接树形控件的选择变化信号
        self.tree_all_state.itemSelectionChanged.connect(self._on_tree_item_selection_changed)

    def show_tree_all_state_context_menu(self, position: QPoint):
        item = self.tree_all_state.itemAt(position)
        if item is None:
            return

        state = item.data(0, Qt.UserRole)
        if state is None:
            return

        menu = QtWidgets.QMenu()
        edit_action = QtWidgets.QAction("修改状态名", self)
        add_action = QtWidgets.QAction("添加子状态", self)
        delete_action = QtWidgets.QAction("删除状态", self)

        edit_action.triggered.connect(lambda: self.edit_state(item, state))
        add_action.triggered.connect(lambda: self.add_sub_state(item, state))
        delete_action.triggered.connect(lambda: self.delete_state(item, state))

        menu.addAction(edit_action)
        menu.addAction(add_action)
        menu.addAction(delete_action)

        menu.exec_(self.tree_all_state.viewport().mapToGlobal(position))

    def edit_state(self, item, state):
        self._add_state(father_state=None, is_edit=True)

    def add_sub_state(self, parent_item, parent_state):
        self._add_state(father_state=parent_state, is_edit=False)

    def delete_state(self, item, state: State):
        if state.name == self.state_manager.root_state.name:
            QtWidgets.QMessageBox.warning(
                self,
                "警告",
                "状态机根节点不能删除！",
                QtWidgets.QMessageBox.Ok
            )
            return

        reply = QtWidgets.QMessageBox.question(self, "删除确认", f"确定要删除状态 '{state.name}' 和其所有子状态，以及有关的转移吗？",
                                     QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

        if reply == QtWidgets.QMessageBox.Yes:

            self.state_manager.remove_state(state.name)
            parent_item = item.parent()
            if parent_item:
                parent_state = self.state_manager.get_state(state.parent)
                parent_state.children.remove(state.name)
                parent_item.removeChild(item)
            else:
                index = self.tree_all_state.indexOfTopLevelItem(item)
                self.tree_all_state.takeTopLevelItem(index)
            # 更新表格
            self._display_transition_lifecycle_details()

    def _init_button_state_machine_add_state(self):
        self.button_add_state.clicked.connect(lambda: self._buton_add_state())

    def _init_button_state_machine_export(self):
        self.button_export_state_machine.clicked.connect(lambda: self._export_statechart())

    def _init_button_state_machine_validation(self):
        self.button_validate_state_machine.clicked.connect(lambda: self._validate_statechart())

    def _init_button_state_machine_graph_gen(self):
        self.button_graph_gen.clicked.connect(lambda: self._graph_gen())

    def _init_button_state_machine_expand_all(self):
        self.button_expand_all_state.setToolTip("展开所有")
        expand_icon = qta.icon('fa5s.angle-down', color='#000000')
        self.button_expand_all_state.setIcon(expand_icon)
        self.button_expand_all_state.setIconSize(PyQt5.Qt.QSize(25, 25))
        self.button_expand_all_state.clicked.connect(lambda: self._expand_all_state(self.tree_all_state))

    def _init_button_state_machine_fold_all(self):
        self.button_fold_all_state.setToolTip("折叠所有")
        fold_icon = qta.icon('fa5s.angle-up', color='#000000')
        self.button_fold_all_state.setIcon(fold_icon)
        self.button_fold_all_state.setIconSize(PyQt5.Qt.QSize(25, 25))
        self.button_fold_all_state.clicked.connect(lambda: self._fold_all_state(self.tree_all_state))

    def _expand_all_state(self, tree_widget: QtWidgets.QTreeWidget):
        tree_widget.expandAll()

    def _fold_all_state(self, tree_widget: QtWidgets.QTreeWidget):
        tree_widget.collapseAll()

    def _display_transition_lifecycle_details(self):
        try:
            if self.state_manager is None:
                return
            cur_state = self._get_pro_state()
            if cur_state is None:
                return
            self.edit_state_transition.setText(cur_state.transition)
            self.edit_lifecycle.setText(cur_state.lifecycle)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"更新状态机详情时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _buton_add_state(self):
        father_state = self._get_pro_state()
        if father_state is None and self.state_manager.get_root_state() is not None:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                "状态机中只能有一个根状态",
                QtWidgets.QMessageBox.Ok
            )
            return
        else:
            self._add_state(father_state, False)

    def _add_state(self, father_state: Optional[State], is_edit = False):
        """
        保存状态信息，并使用QTreeWidget展示状态
        """
        try:
            if is_edit:
                # 获取当前编辑状态
                pro_state = self._get_pro_state()
                if pro_state is None:
                    QtWidgets.QMessageBox.warning(self, "提示", "请先选择要编辑的状态")
                    return
                    
                dialog = DialogEditState(self, state_manager=self.state_manager, is_edit=True, initial_data=pro_state)
                if dialog.exec_() == QtWidgets.QDialog.Accepted:
                    new_state_name = dialog.get_state_name()
                    # 改变原状态的名字
                    try:
                        self.state_manager.rename_state(pro_state.name, new_state_name)
                        cur_tree_item = self.tree_all_state.currentItem()
                        cur_tree_item.setText(0, new_state_name)
                    except Exception as e:
                        QtWidgets.QMessageBox.critical(
                            self,
                            "错误",
                            f"编辑状态时发生错误：\n{str(e)}",
                            QtWidgets.QMessageBox.Ok
                        )
                        return
            else:
                # 添加新状态
                dialog = DialogEditState(self, state_manager=self.state_manager, is_edit=False, initial_data=None)
                if dialog.exec_() == QtWidgets.QDialog.Accepted:
                    new_state_name = dialog.get_state_name()
                    try:
                        new_state = State(new_state_name)
                        self.state_manager.add_state(father_state, new_state)
                        if self.state_manager.get_root_state() is None:
                            self.state_manager.root_state = new_state
                        cur_state_item = QtWidgets.QTreeWidgetItem([new_state_name])
                        cur_state_item.setData(0, Qt.UserRole, new_state)
                        # 如果是添加子状态：
                        if father_state is not None:
                            father_item = self.tree_all_state.currentItem()
                            father_item.addChild(cur_state_item)
                        else:
                            self.tree_all_state.addTopLevelItem(cur_state_item)
                    except Exception as e:
                        QtWidgets.QMessageBox.critical(
                            self,
                            "错误",
                            f"添加状态时发生错误：\n{str(e)}",
                            QtWidgets.QMessageBox.Ok
                        )
                        return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"操作状态时发生未知错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _import_statechart(self):
        """导入 fcstm 文件"""
        try:
            # 检查上次使用的路径是否存在
            if not os.path.exists(self.state_machine_file_path):
                self.state_machine_file_path = "./"
                
            file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, 
                "选择fcstm文件",
                self.state_machine_file_path, 
                "fcstm Files (*.fcstm);;All Files (*)"
            )
            if not file_path:
                return
                
            # 更新上次使用的路径
            self.state_machine_file_path = os.path.dirname(file_path)
            
            try:
                # 使用新的DSL转换功能
                self.state_manager = dsl_to_state_manager(file_path)
                # 更新UI界面
                update_ui_from_state_manager(self, self.state_manager)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "导入失败",
                    f"解析fcstm文件时发生错误：\n{str(e)}",
                    QtWidgets.QMessageBox.Ok
                )
                return
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"导入状态机时发生未知错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _export_statechart(self):
        try:
            # 检查上次使用的路径是否存在
            if not os.path.exists(self.state_machine_file_path):
                self.state_machine_file_path = "./"
                
            options = QtWidgets.QFileDialog.Options()
            file_name, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "导出状态机",
                self.state_machine_file_path,
                "fcstm Files (*.fcstm);;Word Documents (*.docx);;Excel Files (*.xlsx);;All Files (*)",
                options=options
            )
            
            if not file_name:
                return
                
            # 更新上次使用的路径
            self.state_machine_file_path = os.path.dirname(file_name)
            try:
                if selected_filter == "fcstm Files (*.fcstm)":
                    # 确保文件名以 .fcstm 结尾
                    if not file_name.endswith('.fcstm'):
                        file_name += '.fcstm'

                    # 将StateManager转换为fcstm格式
                    dsl_str = state_manager_to_dsl(self.state_manager)
                    with open(file_name, 'w', encoding='utf-8') as f:
                        f.write(dsl_str)

                elif selected_filter == "Word Documents (*.docx)":
                    # 确保文件名以 .docx 结尾
                    if not file_name.endswith('.docx'):
                        file_name += '.docx'
                    export_statechart_to_word(self.state_manager, file_name)
                elif selected_filter == "Excel Files (*.xlsx)":
                    # 确保文件名以 .xlsx 结尾
                    if not file_name.endswith('.xlsx'):
                        file_name += '.xlsx'
                    export_statechart_to_excel(self.state_manager, file_name)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "导出失败",
                    f"导出文件时发生错误：\n{str(e)}",
                    QtWidgets.QMessageBox.Ok
                )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"导出状态机时发生未知错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _validate_statechart(self):
        try:
            if self.state_manager is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先创建或导入状态机！",
                    QtWidgets.QMessageBox.Ok
                )
                return
            #通过pyfcstm中的解析dsl文件来判断
            dsl_str = state_manager_to_dsl(self.state_manager)
            ast_node = parse_with_grammar_entry(dsl_str, entry_name='state_machine_dsl')
            _ = parse_dsl_node_to_state_machine(ast_node)
            QtWidgets.QMessageBox.information(self, "提示", "验证无错误")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"{str(e)}")

    def _graph_gen(self):
        try:
            if self.state_manager is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先创建或导入状态机！",
                    QtWidgets.QMessageBox.Ok
                )
                return
            dialog_show_graph = DialogShowGraph(self, self.state_manager)
            dialog_show_graph.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"生成状态图时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _on_tree_item_selection_changed(self):
        """
        当树形控件中的选择发生变化时，更新转移信息和生命周期信息文本框
        """
        try:
            if self.state_manager is None:
                return

            current_state = self._get_pro_state()

            if current_state is None:
                # 如果没有选中项，清空文本框
                self.edit_state_transition.clear()
                self.edit_lifecycle.clear()
                return
                
            # 更新转移信息
            self.edit_state_transition.setText(current_state.transition)
            # 更新生命周期信息
            self.edit_lifecycle.setText(current_state.lifecycle)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"更新状态信息时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _on_transition_text_changed(self):
        """
        当转移信息文本框内容变化时，保存到当前选中的状态
        """
        try:
            if self.state_manager is None:
                return
                
            current_state = self._get_pro_state()
            if current_state is None:
                return
                
            # 获取文本框内容并保存到状态对象
            transition_text = self.edit_state_transition.toPlainText()
            current_state.transition = transition_text
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"保存转移信息时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _on_lifecycle_text_changed(self):
        """
        当生命周期信息文本框内容变化时，保存到当前选中的状态
        """
        try:
            if self.state_manager is None:
                return
                
            current_state = self._get_pro_state()
            if current_state is None:
                return
                
            # 获取文本框内容并保存到状态对象
            lifecycle_text = self.edit_lifecycle.toPlainText()
            current_state.lifecycle = lifecycle_text
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"保存生命周期信息时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _on_var_def_text_changed(self):
        """
        当变量定义文本框内容变化时，保存到StateManager
        """
        try:
            if self.state_manager is None:
                return
                
            # 获取文本框内容并保存到StateManager
            var_def_text = self.edit_var_def.toPlainText()
            self.state_manager.variable_definitions = var_def_text
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"保存变量定义时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _get_pro_state(self) -> Optional[State]:
        # 获得当前Tree中选择的item
        selected_state_item = self.tree_all_state.currentItem()
        # 若没有选中状态，则返回None
        if not selected_state_item:
            return None
        pro_state = selected_state_item.data(0, Qt.UserRole)
        return pro_state