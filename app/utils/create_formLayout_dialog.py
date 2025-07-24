from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QTimerEvent, Qt

def create_formlayout_dialog(parent, window_title, label_data, edit_data):
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(window_title)
    layout = QtWidgets.QFormLayout(dialog)
    # 移除 "?" 按钮
    dialog.setWindowFlags(dialog.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
    # 创建输入框
    entries = []
    # 为每一列创建输入框
    for col in range(len(label_data)):
        header = label_data[col]
        line_edit = QtWidgets.QLineEdit(edit_data[col])
        layout.addRow(header, line_edit)
        entries.append(line_edit)

    # 添加确定和取消按钮
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
        QtCore.Qt.Horizontal, dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)

    result = dialog.exec_()
    if result == QtWidgets.QDialog.Accepted:
        data = [entry.text() for entry in entries]
        return True, data
    else:
        return False, None