import sys
import os
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import Qt, QRect, QSize
from PyQt5.QtWidgets import QWidget, QPlainTextEdit, QTextEdit
from PyQt5.QtGui import QColor, QPainter, QTextFormat, QFont, QSyntaxHighlighter, QTextCharFormat

from app.ui import UIDialogShowError

# 行号区域组件
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

# 带行号的代码编辑器
class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        
        self.update_line_number_area_width(0)
        self.highlight_current_line()
        
        # 设置字体
        font = QFont("Courier New", 10)
        self.setFont(font)
        
        # 设置只读
        self.setReadOnly(True)
        
        # 设置tab为4个空格
        self.setTabStopWidth(self.fontMetrics().width(' ') * 4)

    def line_number_area_width(self):
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1
        
        space = 3 + self.fontMetrics().width('9') * digits
        return space

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor(Qt.lightGray).lighter(120))
        
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(Qt.black)
                painter.drawText(0, top, self.line_number_area.width() - 2, 
                                self.fontMetrics().height(),
                                Qt.AlignRight, number)
            
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        extra_selections = []
        
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor(Qt.yellow).lighter(160)
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        
        self.setExtraSelections(extra_selections)

# 错误语法高亮器
class ErrorHighlighter(QSyntaxHighlighter):
    def __init__(self, document, error_lines=None):
        super().__init__(document)
        self.error_lines = error_lines or []
        
        # 错误行的格式
        self.error_format = QTextCharFormat()
        self.error_format.setBackground(QColor(255, 200, 200))  # 浅红色背景
        self.error_format.setForeground(Qt.red)  # 红色文字

    def highlightBlock(self, text):
        # 获取当前块的行号
        block_number = self.currentBlock().blockNumber()
        
        # 检查是否是错误行
        if block_number + 1 in self.error_lines:  # +1 因为行号从1开始，blockNumber从0开始
            self.setFormat(0, len(text), self.error_format)

class DialogShowError(QtWidgets.QDialog, UIDialogShowError):
    def __init__(self, parent=None, dsl_code="", error_info="", error_lines=None):
        """
        初始化错误展示对话框
        
        Args:
            parent: 父窗口
            dsl_code: DSL代码内容
            error_info: 错误信息内容
            error_lines: 错误行号列表，如 [5, 10, 15]
        """
        QtWidgets.QDialog.__init__(self, parent)
        self.setupUi(self)
        self.error_lines = error_lines or []
        
        # 去掉对话框右上角的问号标志
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        # 设置布局
        self.dsl_code_layout = QtWidgets.QVBoxLayout(self.widget_dsl_code)
        self.error_layout = QtWidgets.QVBoxLayout(self.widget_error)
        
        # 创建代码编辑器
        self.dsl_code_editor = CodeEditor()
        self.error_editor = CodeEditor()
        
        # 添加到布局
        self.dsl_code_layout.addWidget(self.dsl_code_editor)
        self.error_layout.addWidget(self.error_editor)
        
        # 设置内容
        self.dsl_code_editor.setPlainText(dsl_code)
        self.error_editor.setPlainText(error_info)
        
        # 添加错误高亮
        self.error_highlighter = ErrorHighlighter(self.dsl_code_editor.document(), self.error_lines)
        
        # 设置窗口标题
        self.setWindowTitle("状态机错误")
        
        # 调整大小
        self.resize(900, 600)
        
        # 高亮错误行
        self.highlight_error_lines()
    
    def highlight_error_lines(self):
        """高亮错误行并滚动到第一个错误行"""
        if not self.error_lines:
            return
            
        # 滚动到第一个错误行
        first_error_line = min(self.error_lines)
        cursor = QtGui.QTextCursor(self.dsl_code_editor.document().findBlockByLineNumber(first_error_line - 1))
        self.dsl_code_editor.setTextCursor(cursor)
        self.dsl_code_editor.centerCursor()

# 用法示例
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    
    # 示例代码和错误
    dsl_code = """def int a = 0;
def int b = 0;
state Test {
    state A {
        ! * -> B : if [a > 1];
        state B {
            ! * -> C : if [b > 2] effect {
                b = 3;
            }
            state C;
        }
    }
    state D;
    ! * -> D : if [a == 0];
    ! D -> A : if [b == 0] effect {
        a = 1;
    }
}"""
    
    error_info = """Error 1: Syntax error at line 5, column 20: mismatched input 'if' expecting {':', '::'}
Error 2: Syntax error at line 14, column 15: mismatched input 'if' expecting {':', '::'}"""
    
    error_lines = [5, 14]  # 错误行号
    
    dialog = DialogShowError(dsl_code=dsl_code, error_info=error_info, error_lines=error_lines)
    dialog.exec_()
