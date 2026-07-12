"""Frozen-product GUI acceptance workflow driver."""

from __future__ import unicode_literals

import hashlib
import json
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtTest, QtWidgets

from app.model.session import ValidationState
from app.widget import AppMainWindow, DialogCodeGen, DialogExport


REPORT_SCHEMA = "fcstm-gui.acceptance-check-report"
REPORT_VERSION = 1

_SOURCE = """def int count = 0;
state Root {
    state Idle;
    state Running;
    [*] -> Idle;
    Idle -> Running :: Start effect { count = count + 1; }
    Running -> [*] :: Stop;
}
"""


def _parse_viewport(value):
    try:
        width, height = str(value).lower().split("x", 1)
        width, height = int(width), int(height)
    except (TypeError, ValueError):
        raise ValueError("viewport must use WIDTHxHEIGHT")
    if width < 640 or height < 480:
        raise ValueError("viewport is too small")
    return width, height


def _wait_signal(signal, trigger, timeout_ms=20000, accept=None):
    loop = QtCore.QEventLoop()
    payload = []
    timed_out = []

    def finished(*args):
        if accept is not None and not accept(*args):
            return
        payload.append(args)
        loop.quit()

    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (timed_out.append(True), loop.quit()))
    signal.connect(finished)
    try:
        QtCore.QTimer.singleShot(0, trigger)
        timer.start(timeout_ms)
        loop.exec_()
    finally:
        timer.stop()
        try:
            signal.disconnect(finished)
        except (TypeError, RuntimeError):
            pass
    if timed_out or not payload:
        raise TimeoutError("GUI operation did not finish within {} ms".format(timeout_ms))
    return payload[0]


def _press(button):
    button.setFocus(QtCore.Qt.TabFocusReason)
    QtTest.QTest.keyClick(button, QtCore.Qt.Key_Space)


def _keyboard_replace(editor, text):
    editor.setFocus(QtCore.Qt.TabFocusReason)
    QtWidgets.QApplication.clipboard().setText(text)
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key_V, QtCore.Qt.ControlModifier)


def _screenshot(widget, artifact_dir, name):
    path = artifact_dir / (name + ".png")
    image = widget.grab()
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError("failed to capture " + name)
    data = path.read_bytes()
    if len(data) < 1000 or len(set(data[100:])) < 8:
        raise RuntimeError("captured screenshot is blank or incomplete")
    return _artifact(path, artifact_dir)


def _artifact(path, artifact_dir):
    path = Path(path)
    data = path.read_bytes()
    return {
        "path": path.relative_to(artifact_dir).as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _write_json(path, payload):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(str(temporary), str(target))
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


class AcceptanceDriver(object):
    def __init__(self, artifact_dir, viewport):
        self.artifact_dir = Path(artifact_dir).resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.viewport = viewport
        self.results = []
        self.artifacts = []
        self.context = {}
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.app.setQuitOnLastWindowClosed(False)
        self.source_path = self.artifact_dir / "acceptance.fcstm"
        self.source_path.write_text(_SOURCE, encoding="utf-8")
        settings = QtCore.QSettings(
            str(self.artifact_dir / "acceptance-settings.ini"),
            QtCore.QSettings.IniFormat,
        )
        self.window = AppMainWindow(settings=settings)
        self.window.resize(*viewport)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()

    def run_item(self, name, function):
        started = time.time()
        print('acceptance START ' + name, flush=True)
        try:
            detail = function()
            status = "passed"
        except BaseException as error:
            detail = "{}: {}".format(type(error).__name__, error)
            status = "failed"
            traceback.print_exc()
        self.results.append(
            {
                "name": name,
                "status": status,
                "duration_ms": int((time.time() - started) * 1000),
                "detail": str(detail),
            }
        )
        print('acceptance {} {} ({})'.format(status.upper(), name, detail), flush=True)

    def run(self):
        items = (
            ("workflow.document-open", self.document_open),
            ("workflow.model-edit-undo-redo", self.model_edit),
            ("workflow.structured-diagnostics", self.diagnostics),
            ("workflow.graph-refresh", self.graph),
            ("workflow.ordinary-simulation", self.simulation),
            ("workflow.dynamic-validation", self.dynamic_validation),
            ("workflow.code-generation", self.generation),
            ("workflow.unified-export", self.unified_export),
            ("workflow.task-results", self.task_results),
            ("workflow.failure-recovery", self.failure_recovery),
            ("geometry.viewport-accessibility", self.geometry),
        )
        for name, function in items:
            self.run_item(name, function)
        return self.results

    def document_open(self):
        original = QtWidgets.QFileDialog.getOpenFileName
        QtWidgets.QFileDialog.getOpenFileName = staticmethod(
            lambda *args, **kwargs: (str(self.source_path), "fcstm Files (*.fcstm)")
        )
        try:
            _wait_signal(
                self.window.document_load_finished,
                lambda: QtTest.QTest.keySequence(
                    self.window, self.window.action_import_state_machine.shortcut()
                ),
            )
        finally:
            QtWidgets.QFileDialog.getOpenFileName = original
        session = self.window.document_session
        if session is None or session.current_valid_snapshot is None:
            raise RuntimeError("keyboard open did not install a valid document")
        if self.window.source_editor.toPlainText() != _SOURCE:
            raise RuntimeError("opened source text differs from file bytes")
        self.artifacts.append(
            _screenshot(self.window, self.artifact_dir, "01-open-{}x{}".format(*self.viewport))
        )
        return "opened revision {} through Ctrl+O".format(session.source_revision)

    def model_edit(self):
        editor = self.window.source_editor
        self.window.workspace_tabs.setCurrentWidget(self.window.source_workspace)
        editor.setFocus(QtCore.Qt.TabFocusReason)
        editor.moveCursor(QtGui.QTextCursor.End)
        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return),
            accept=self._is_current_validation,
        )
        edited = editor.toPlainText()
        if edited != _SOURCE + "\n":
            raise RuntimeError("keyboard edit did not update source")
        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keySequence(editor, self.window.action_undo.shortcut()),
            accept=self._is_current_validation,
        )
        if editor.toPlainText() != _SOURCE:
            raise RuntimeError("keyboard undo did not restore source")
        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keySequence(editor, self.window.action_redo.shortcut()),
            accept=self._is_current_validation,
        )
        if editor.toPlainText() != edited:
            raise RuntimeError("keyboard redo did not restore edit")
        return "edit, undo, redo through keyboard; revision {}".format(
            self.window.document_session.source_revision
        )

    def diagnostics(self):
        editor = self.window.source_editor

        def type_invalid():
            _keyboard_replace(editor, "state Broken { state ; }")

        _wait_signal(
            self.window.document_validation_finished,
            type_invalid,
            accept=self._is_current_validation,
        )
        if self.window.document_session.validation_state is not ValidationState.INVALID_SYNTAX:
            raise RuntimeError("invalid keyboard edit did not enter syntax state")
        self.window.workspace_tabs.setCurrentWidget(self.window.diagnostics_workspace)
        self.app.processEvents()
        panel = self.window.diagnostics_panel
        if panel.table.rowCount() < 1:
            raise RuntimeError("structured diagnostics table is empty")
        locate = panel.table.cellWidget(0, panel.COLUMN_ACTION)
        if locate is None or not locate.isEnabled():
            raise RuntimeError("diagnostic location action unavailable")
        _press(locate)
        if not editor.hasFocus() or not editor.textCursor().hasSelection():
            raise RuntimeError("diagnostic locate did not focus a source range")
        self.artifacts.append(
            _screenshot(self.window, self.artifact_dir, "02-diagnostics-{}x{}".format(*self.viewport))
        )

        def restore_valid():
            _keyboard_replace(editor, _SOURCE)

        _wait_signal(
            self.window.document_validation_finished,
            restore_valid,
            accept=self._is_current_validation,
        )
        if self.window.document_session.current_valid_snapshot is None:
            raise RuntimeError("valid source recovery did not restore snapshot")
        return "syntax diagnostic located and valid source recovered"

    def graph(self):
        result = _wait_signal(
            self.window.graph_task_finished,
            lambda: self.window.action_graph_gen.trigger(),
        )[0]
        if result.status.value != "success":
            raise RuntimeError(
                "graph refresh {}: {}".format(result.status.value, result.error)
            )
        scene = self.window.graph_panel.view.scene()
        if scene is None or scene.sceneRect().isEmpty():
            raise RuntimeError("graph refresh produced no visible scene")
        self.artifacts.append(
            _screenshot(self.window, self.artifact_dir, "03-graph-{}x{}".format(*self.viewport))
        )
        return "graph rendered through action and visible in central tab"

    def _is_current_validation(self, result):
        session = self.window.document_session
        return bool(
            session is not None
            and result.stamp.session_id == session.session_id
            and result.stamp.source_revision == session.source_revision
        )

    def simulation(self):
        panel = self.window.simulation_panel
        self.window.workspace_tabs.setCurrentWidget(self.window.simulation_workspace)
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.initialize_button),
        )
        panel.event_edit.setText("Start")
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.cycle_button),
        )
        if panel.transcript_table.rowCount() < 2 or "Root.Running" not in panel.snapshot_label.text():
            raise RuntimeError("ordinary simulation transcript/state is incomplete")
        self.artifacts.append(
            _screenshot(self.window, self.artifact_dir, "04-simulation-{}x{}".format(*self.viewport))
        )
        return "initialized and advanced real SimulationRuntime"

    def dynamic_validation(self):
        panel = self.window.dynamic_validation_panel
        self.window.workspace_tabs.setCurrentWidget(self.window.dynamic_validation_workspace)
        _wait_signal(
            self.window.dynamic_validation_finished,
            lambda: _press(panel.run_suite_button),
        )
        payload = json.loads(panel.report_json())
        if payload["report"]["status"] != "passed" or len(payload["report"]["cases"]) != 4:
            raise RuntimeError("four packaged dynamic cases did not pass")
        report_path = self.artifact_dir / "dynamic-validation-report.json"
        report_path.write_text(panel.report_json(), encoding="utf-8")
        self.artifacts.append(_artifact(report_path, self.artifact_dir))
        self.artifacts.append(
            _screenshot(self.window, self.artifact_dir, "05-dynamic-{}x{}".format(*self.viewport))
        )
        return "4 cases passed with expected/actual report"

    def generation(self):
        dialog = DialogCodeGen(
            self.window, self.window.generation_service.list_templates()
        )
        dialog.generate_requested.connect(
            lambda request: self.window._start_generation(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("code-generation")
        )
        output = self.artifact_dir / "generated-python"
        dialog.language_combo.setCurrentIndex(
            dialog.language_combo.findData("python")
        )
        dialog.output_edit.setText(str(output))
        dialog.show()
        _wait_signal(
            self.window.generation_finished,
            lambda: _press(dialog.generate_button),
        )
        if dialog.result_table.rowCount() < 1 or not (output / "machine.py").is_file():
            raise RuntimeError("packaged Python template generated no runtime")
        self.artifacts.append(
            _screenshot(dialog, self.artifact_dir, "06-generation-dialog")
        )
        for path in sorted(item for item in output.rglob("*") if item.is_file()):
            self.artifacts.append(_artifact(path, self.artifact_dir))
        dialog.close()
        return "Python packaged template generated {} files".format(
            dialog.result_table.rowCount()
        )

    def unified_export(self):
        dialog = DialogExport(self.window, dynamic_available=True)
        dialog.export_requested.connect(
            lambda request: self.window._start_unified_export(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("unified-export")
        )
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("inspect-json"))
        target = self.artifact_dir / "inspect-report.json"
        dialog.path_edit.setText(str(target))
        dialog.show()
        _wait_signal(
            self.window.unified_export_finished,
            lambda: _press(dialog.start_button),
        )
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("inspect export schema root is not an object")
        self.artifacts.append(_artifact(target, self.artifact_dir))
        self.artifacts.append(
            _screenshot(dialog, self.artifact_dir, "07-unified-export-dialog")
        )
        dialog.close()
        return "inspect JSON exported through unified dialog"

    def task_results(self):
        dock = self.window.task_result_dock
        dock.show()
        dock.refresh()
        self.app.processEvents()
        if dock.table.rowCount() < 5:
            raise RuntimeError("explicit task history is incomplete")
        dock.table.setCurrentCell(0, 0)
        dock.table.selectRow(0)
        _press(dock.copy_button)
        copied = self.app.clipboard().text()
        if 'task_id' not in copied or str(self.artifact_dir) in copied:
            raise RuntimeError("task copy is empty or leaks the workspace path")
        self.artifacts.append(
            _screenshot(self.window, self.artifact_dir, "08-task-results-{}x{}".format(*self.viewport))
        )
        return "{} task rows, redacted keyboard copy".format(dock.table.rowCount())

    def failure_recovery(self):
        target = self.artifact_dir / "existing.fcstm"
        target.write_text("old", encoding="utf-8")
        dialog = DialogExport(self.window)
        dialog.export_requested.connect(
            lambda request: self.window._start_unified_export(request, dialog)
        )
        dialog.path_edit.setText(str(target))
        dialog.show()
        result = _wait_signal(
            self.window.unified_export_finished,
            lambda: _press(dialog.start_button),
        )[0]
        if result.status.value != 'failed' or target.read_text(encoding='utf-8') != 'old':
            raise RuntimeError("failed export modified the existing target")
        dialog.close()
        return "existing target preserved after expected export failure"

    def geometry(self):
        self.window.resize(*self.viewport)
        self.app.processEvents()
        names = (
            'source_editor', 'diagnostics_table', 'graph_view',
            'simulation_transcript_table', 'dynamic_result_table',
            'task_result_table',
        )
        controls = []
        window_rect = self.window.rect()
        for name in names:
            widget = self.window.findChild(QtWidgets.QWidget, name)
            if widget is None:
                raise RuntimeError('missing core control ' + name)
            point = widget.mapTo(self.window, QtCore.QPoint(0, 0))
            rect = QtCore.QRect(point, widget.size())
            controls.append(
                {
                    'object_name': name,
                    'visible': widget.isVisible(),
                    'enabled': widget.isEnabled(),
                    'x': rect.x(),
                    'y': rect.y(),
                    'width': rect.width(),
                    'height': rect.height(),
                    'inside_window': window_rect.intersects(rect),
                }
            )
            if widget.width() <= 0 or widget.height() <= 0 or not window_rect.intersects(rect):
                raise RuntimeError(name + ' has invalid geometry')
        buttons = []
        for button in self.window.findChildren(QtWidgets.QAbstractButton):
            if not button.isVisible():
                continue
            if not button.accessibleName() or not button.toolTip():
                raise RuntimeError('visible button lacks accessibility metadata: ' + button.objectName())
            text = button.text()
            fits = True
            if text:
                fits = button.fontMetrics().horizontalAdvance(text) <= max(0, button.width() - 12)
            buttons.append({'object_name': button.objectName(), 'text_fits': fits})
            if not fits:
                raise RuntimeError('visible button text is clipped: ' + button.objectName())
        self.context['geometry'] = {
            'viewport': '{}x{}'.format(*self.viewport),
            'qt_scale_factor': os.environ.get('QT_SCALE_FACTOR', '1'),
            'controls': controls,
            'buttons': buttons,
        }
        return '{} controls and {} visible buttons checked'.format(len(controls), len(buttons))

    def close(self):
        original = QtWidgets.QMessageBox.question
        QtWidgets.QMessageBox.question = staticmethod(
            lambda *args, **kwargs: QtWidgets.QMessageBox.Discard
        )
        try:
            self.window.close()
            self.app.processEvents()
        finally:
            QtWidgets.QMessageBox.question = original


def run_acceptance_check(json_report, artifact_dir=None, viewport='1280x720'):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    viewport_size = _parse_viewport(viewport)
    if artifact_dir is None:
        if json_report:
            artifact_dir = str(Path(json_report).resolve().parent / 'acceptance-artifacts')
        else:
            artifact_dir = tempfile.mkdtemp(prefix='fcstm-gui-acceptance-')
    started_at = time.time()
    driver = AcceptanceDriver(artifact_dir, viewport_size)
    try:
        results = driver.run()
    finally:
        driver.close()
    failures = [item for item in results if item['status'] == 'failed']
    report = {
        'schema': REPORT_SCHEMA,
        'version': REPORT_VERSION,
        'status': 'failed' if failures else 'passed',
        'started_at': started_at,
        'duration_ms': int((time.time() - started_at) * 1000),
        'platform': {
            'system': platform.system(),
            'release': platform.release(),
            'machine': platform.machine(),
            'python': platform.python_version(),
            'frozen': bool(getattr(sys, 'frozen', False)),
        },
        'viewport': '{}x{}'.format(*viewport_size),
        'qt_scale_factor': os.environ.get('QT_SCALE_FACTOR', '1'),
        'counts': {
            'total': len(results),
            'passed': len(results) - len(failures),
            'failed': len(failures),
        },
        'results': results,
        'geometry': driver.context.get('geometry'),
        'artifacts': driver.artifacts,
    }
    if json_report:
        _write_json(json_report, report)
    print(
        'fcstm-gui acceptance-check: {} passed / {} failed - {}'.format(
            report['counts']['passed'],
            report['counts']['failed'],
            report['status'].upper(),
        )
    )
    return 1 if failures else 0
