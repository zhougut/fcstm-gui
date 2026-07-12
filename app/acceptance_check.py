"""Frozen-product GUI acceptance workflow driver."""

from __future__ import unicode_literals

import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import time
import traceback
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtTest, QtWidgets

from app.model.session import ValidationState
from app.source import SourceDocument
from app.utils.application_font import (
    APPLICATION_FONT_POINT_SIZE,
    EXPECTED_FAMILY,
)
from app.widget import AppMainWindow, DialogCodeGen, DialogExport, DialogNumericFormula
from app.widget.dialog_add_lifecycle import DialogAddLifecycle
from app.widget.dialog_add_transition import DialogAddTransition


REPORT_SCHEMA = "fcstm-gui.acceptance-check-report"
REPORT_VERSION = 1

_COCOA_NATIVE_OVERLAP_PAIRS = {
    "ordinary_simulation_panel": frozenset(
        {
        ("simulation_cycle_button", "simulation_initialize_button"),
        ("simulation_cycle_button", "simulation_run_button"),
        ("simulation_pause_button", "simulation_run_button"),
        ("simulation_pause_button", "simulation_reset_button"),
        ("simulation_cancel_button", "simulation_reset_button"),
        }
    ),
    "dynamic_validation_panel": frozenset(
        {
            ("dynamic_run_case_button", "dynamic_run_user_button"),
            ("dynamic_run_case_button", "dynamic_run_suite_button"),
            ("dynamic_cancel_button", "dynamic_run_suite_button"),
            ("dynamic_cancel_button", "dynamic_export_button"),
        }
    ),
}

_CONTROL_ACCEPTANCE = {
    "simulation_initialize_button": "simulation.initialize",
    "simulation_cycle_button": "simulation.step",
    "simulation_run_button": "simulation.run",
    "simulation_pause_button": "simulation.pause",
    "simulation_reset_button": "simulation.reset",
    "simulation_cancel_button": "simulation.stop",
    "dynamic_run_user_button": "dynamic.user",
    "dynamic_run_case_button": (
        "dynamic.case.design_evented_pseudo_chain_invalid_then_valid"
    ),
    "dynamic_run_suite_button": "export.dynamic-json",
    "dynamic_cancel_button": "cancel.dynamic",
    "dynamic_export_button": "dynamic.export",
}

_SOURCE = """def int count = 0;
state Root {
    state Idle;
    state Running;
    [*] -> Idle;
    Idle -> Running :: Start effect { count = count + 1; }
    Running -> [*] :: Stop;
}
"""


def _is_preapproved_native_overlap(
    platform_system, qt_platform, parent_name, widget_names
):
    return bool(
        platform_system == "Darwin"
        and qt_platform == "cocoa"
        and tuple(sorted(widget_names))
        in _COCOA_NATIVE_OVERLAP_PAIRS.get(parent_name, ())
    )


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
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Backspace)
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key_V, QtCore.Qt.ControlModifier)


def _select_combo_data(combo, value):
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError("combo value is unavailable: {}".format(value))
    combo.setFocus(QtCore.Qt.TabFocusReason)
    QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Home)
    for _unused in range(index):
        QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Down)
    QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Tab)
    if combo.currentData() != value:
        raise RuntimeError("keyboard combo selection failed: {}".format(value))


def _error_chain(error):
    chain = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(
            {
                "type": type(current).__name__,
                "message": str(current),
            }
        )
        current = current.__cause__ or current.__context__
    return chain


def _schedule_message_box_accept():
    attempts = [0]

    def accept_message():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMessageBox) and widget.isVisible():
                button = widget.button(QtWidgets.QMessageBox.Yes)
                if button is None:
                    button = widget.button(QtWidgets.QMessageBox.Ok)
                if button is not None:
                    _press(button)
                else:
                    QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Enter)
                return
        if attempts[0] < 100:
            QtCore.QTimer.singleShot(10, accept_message)

    QtCore.QTimer.singleShot(0, accept_message)


def _schedule_file_dialog_path(path, remove_after_accept=False):
    attempts = [0]
    phase = [0]
    target = Path(path)

    def remove_target():
        try:
            target.unlink()
        except OSError:
            pass

    def enter_path():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QFileDialog) and widget.isVisible():
                editor = widget.findChild(QtWidgets.QLineEdit, "fileNameEdit")
                if editor is None:
                    continue
                button_box = widget.findChild(QtWidgets.QDialogButtonBox)
                accept_button = None
                if button_box is not None:
                    accept_button = next(
                        (
                            button
                            for button in button_box.buttons()
                            if button_box.buttonRole(button)
                            == QtWidgets.QDialogButtonBox.AcceptRole
                        ),
                        None,
                    )
                if phase[0] == 0:
                    if remove_after_accept:
                        widget.accepted.connect(remove_target)
                    widget.setDirectory(str(target.parent))
                    phase[0] = 1
                elif phase[0] == 1:
                    _keyboard_replace(editor, target.name)
                    QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Tab)
                    phase[0] = 2
                elif phase[0] == 2 and attempts[0] >= 100:
                    widget.selectFile(target.name)
                    phase[0] = 3
                elif accept_button is not None and accept_button.isEnabled():
                    QtTest.QTest.mouseClick(
                        accept_button, QtCore.Qt.LeftButton
                    )
                    return
                elif attempts[0] >= 500:
                    widget.reject()
                    return
        if attempts[0] < 500:
            QtCore.QTimer.singleShot(10, enter_path)

    QtCore.QTimer.singleShot(0, enter_path)


def _schedule_file_dialog_cancel():
    attempts = [0]

    def cancel_dialog():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QFileDialog) and widget.isVisible():
                QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Escape)
                return
        if attempts[0] < 300:
            QtCore.QTimer.singleShot(10, cancel_dialog)

    QtCore.QTimer.singleShot(0, cancel_dialog)


def _schedule_message_box_choice(choice):
    attempts = [0]

    def choose():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMessageBox) and widget.isVisible():
                button = widget.button(choice)
                if button is not None:
                    _press(button)
                    return
        if attempts[0] < 300:
            QtCore.QTimer.singleShot(10, choose)

    QtCore.QTimer.singleShot(0, choose)


def _schedule_state_rename_dialog(new_name):
    menu_attempts = [0]
    dialog_attempts = [0]

    def choose_edit():
        menu_attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMenu) and widget.isVisible():
                QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Down)
                QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Enter)
                return
        if menu_attempts[0] < 300:
            QtCore.QTimer.singleShot(10, choose_edit)

    def submit_name():
        dialog_attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            editor = getattr(widget, "edit_state_name", None)
            button = getattr(widget, "button_accept", None)
            if editor is not None and button is not None and widget.isVisible():
                _keyboard_replace(editor, new_name)
                _press(button)
                return
        if dialog_attempts[0] < 300:
            QtCore.QTimer.singleShot(10, submit_name)

    QtCore.QTimer.singleShot(0, choose_edit)
    QtCore.QTimer.singleShot(0, submit_name)


def _schedule_menu_action(position, confirmation=None):
    attempts = [0]

    def choose():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMenu) and widget.isVisible():
                for _unused in range(position + 1):
                    QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Down)
                if confirmation is not None:
                    _schedule_message_box_choice(confirmation)
                QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Enter)
                return
        if attempts[0] < 300:
            QtCore.QTimer.singleShot(10, choose)

    QtCore.QTimer.singleShot(0, choose)


def _schedule_state_name_dialog(name):
    attempts = [0]

    def submit():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            editor = getattr(widget, "edit_state_name", None)
            button = getattr(widget, "button_accept", None)
            if editor is not None and button is not None and widget.isVisible():
                _keyboard_replace(editor, name)
                _press(button)
                return
        if attempts[0] < 300:
            QtCore.QTimer.singleShot(10, submit)

    QtCore.QTimer.singleShot(0, submit)


def _schedule_transition_dialog(source, target, condition="", action=""):
    attempts = [0]
    filled = [False]

    def submit():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            source_field = getattr(widget, "edit_source_state", None)
            target_field = getattr(widget, "edit_target_state", None)
            button = getattr(widget, "button_accept", None)
            if source_field is not None and target_field is not None and widget.isVisible():
                if not filled[0]:
                    _keyboard_replace(source_field, source)
                    _keyboard_replace(target_field, target)
                    _keyboard_replace(widget.edit_condition, condition)
                    _keyboard_replace(widget.edit_op, action)
                    filled[0] = True
                if button.isEnabled():
                    _schedule_message_box_choice(QtWidgets.QMessageBox.Ok)
                    _press(button)
                    if widget.isVisible():
                        widget.reject()
                    return
        if attempts[0] < 300:
            QtCore.QTimer.singleShot(10, submit)

    QtCore.QTimer.singleShot(0, submit)


def _schedule_lifecycle_dialog(action):
    attempts = [0]
    filled = [False]

    def submit():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            editor = getattr(widget, "lifecycle_formula_editor", None)
            button = getattr(widget, "button_accept", None)
            if editor is not None and button is not None and widget.isVisible():
                if not filled[0]:
                    _keyboard_replace(widget.edit_op, action)
                    filled[0] = True
                if button.isEnabled():
                    _schedule_message_box_choice(QtWidgets.QMessageBox.Ok)
                    _press(button)
                    if widget.isVisible():
                        widget.reject()
                    return
        if attempts[0] < 300:
            QtCore.QTimer.singleShot(10, submit)

    QtCore.QTimer.singleShot(0, submit)


def _schedule_input_dialog_values(values):
    pending = list(values)
    attempts = [0]

    def submit_next():
        attempts[0] += 1
        if not pending:
            return
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QInputDialog) and widget.isVisible():
                editor = widget.findChild(QtWidgets.QLineEdit)
                button_box = widget.findChild(QtWidgets.QDialogButtonBox)
                if editor is None or button_box is None:
                    continue
                _keyboard_replace(editor, pending.pop(0))
                _press(button_box.button(QtWidgets.QDialogButtonBox.Ok))
                attempts[0] = 0
                QtCore.QTimer.singleShot(0, submit_next)
                return
        if attempts[0] < 600:
            QtCore.QTimer.singleShot(10, submit_next)

    QtCore.QTimer.singleShot(0, submit_next)


def _schedule_event_editor(name, display_name):
    attempts = [0]

    def submit():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.objectName() != "event_editor_dialog" or not widget.isVisible():
                continue
            name_edit = widget.findChild(QtWidgets.QLineEdit, "event_name_edit")
            display_edit = widget.findChild(
                QtWidgets.QLineEdit, "event_display_name_edit"
            )
            buttons = widget.findChild(QtWidgets.QDialogButtonBox)
            _keyboard_replace(name_edit, name)
            _keyboard_replace(display_edit, display_name)
            _press(buttons.button(QtWidgets.QDialogButtonBox.Ok))
            return
        if attempts[0] < 300:
            QtCore.QTimer.singleShot(10, submit)

    QtCore.QTimer.singleShot(0, submit)


def _schedule_preview_accept():
    attempts = [0]

    def submit():
        attempts[0] += 1
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if (
                widget.objectName() == "event_transaction_preview_dialog"
                and widget.isVisible()
            ):
                buttons = widget.findChild(QtWidgets.QDialogButtonBox)
                _press(buttons.button(QtWidgets.QDialogButtonBox.Ok))
                return
        if attempts[0] < 600:
            QtCore.QTimer.singleShot(10, submit)

    QtCore.QTimer.singleShot(0, submit)


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
        self._current_evidence = {}
        QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_DontUseNativeDialogs, True)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.app.setQuitOnLastWindowClosed(False)
        self.source_path = None
        self.window = None
        self._case_index = 0
        self._case_name = None

    def _reset_case(self, name, with_document=True):
        if self.window is not None:
            self._close_window()
        self._case_index += 1
        self._case_name = name
        case_slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-")
        case_dir = self.artifact_dir / "fixtures" / "{:03d}-{}".format(
            self._case_index, case_slug
        )
        case_dir.mkdir(parents=True, exist_ok=True)
        self.source_path = case_dir / "acceptance.fcstm"
        self.source_path.write_text(_SOURCE, encoding="utf-8")
        settings = QtCore.QSettings(
            str(case_dir / "settings.ini"), QtCore.QSettings.IniFormat
        )
        self.window = AppMainWindow(settings=settings)
        self.window.resize(*self.viewport)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        if with_document:
            session = self.window.document_service.load(self.source_path)
            self.window._set_active_document_session(session)
            self.app.processEvents()

    def _close_window(self):
        if self.window is None:
            return
        window = self.window
        original = QtWidgets.QMessageBox.question
        QtWidgets.QMessageBox.question = staticmethod(
            lambda *args, **kwargs: QtWidgets.QMessageBox.Discard
        )
        try:
            window.close()
            self.app.processEvents()
            window.deleteLater()
            self.window = None
            QtCore.QCoreApplication.sendPostedEvents(
                window, QtCore.QEvent.DeferredDelete
            )
            self.app.processEvents()
            visible = [
                type(widget).__name__
                for widget in self.app.topLevelWidgets()
                if widget.isVisible()
            ]
            if visible:
                raise RuntimeError(
                    "fresh-window cleanup left visible top-level widgets: {}".format(
                        ", ".join(visible)
                    )
                )
        finally:
            QtWidgets.QMessageBox.question = original
            self.window = None

    def _provenance(self):
        session = getattr(self.window, "document_session", None)
        snapshot = None if session is None else session.current_valid_snapshot
        if snapshot is None and session is not None:
            snapshot = session.last_valid_snapshot
        return {
            "source_revision": None if session is None else session.source_revision,
            "dependency_fingerprint": (
                None if snapshot is None else snapshot.dependency_fingerprint
            ),
        }

    def run_item(self, name, function, with_document=True):
        started = time.time()
        artifact_start = len(self.artifacts)
        self._current_evidence = {}
        print('acceptance START ' + name, flush=True)
        error_chain = []
        try:
            self._reset_case(name, with_document=with_document)
            detail = function()
            status = "passed"
        except BaseException as error:
            detail = "{}: {}".format(type(error).__name__, error)
            status = "failed"
            error_chain = _error_chain(error)
            traceback.print_exc()
        screenshot_name = "item-{:02d}-{}-{}x{}".format(
            len(self.results) + 1,
            re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-"),
            *self.viewport
        )
        try:
            self.artifacts.append(
                _screenshot(self.window, self.artifact_dir, screenshot_name)
            )
        except BaseException as screenshot_error:
            diagnostic = self.artifact_dir / (screenshot_name + "-screenshot-error.txt")
            diagnostic.write_text(str(screenshot_error) + "\n", encoding="utf-8")
            self.artifacts.append(_artifact(diagnostic, self.artifact_dir))
            if status == "passed":
                status = "failed"
                detail = "screenshot failed: {}".format(screenshot_error)
        inventory = list(self.artifacts[artifact_start:])
        result = {
                "name": name,
                "status": status,
                "duration_ms": int((time.time() - started) * 1000),
                "detail": str(detail),
                "evidence": dict(self._current_evidence),
                "error_chain": error_chain,
                "artifacts": inventory,
                "artifact_inventory": inventory,
                "isolation": {
                    "strategy": "fresh-window",
                    "case_index": self._case_index,
                },
            }
        result.update(self._provenance())
        self.results.append(result)
        print('acceptance {} {} ({})'.format(status.upper(), name, detail), flush=True)

    def run(self):
        items = [
            ("document.open", self.document_open, False),
            ("document.recent-reopen", self.recent_reopen, True),
            ("document.cancel-load", self.document_cancel_load, True),
            (
                "document.failed-load-preserves-session",
                self.document_failed_load_preserves_session,
                True,
            ),
            ("dirty.save", lambda: self.dirty_replacement("save"), True),
            ("dirty.discard", lambda: self.dirty_replacement("discard"), True),
            ("dirty.cancel", lambda: self.dirty_replacement("cancel"), True),
            ("source.edit", lambda: self.source_case("edit"), True),
            ("source.undo", lambda: self.source_case("undo"), True),
            ("source.redo", lambda: self.source_case("redo"), True),
            ("source.save", lambda: self.source_case("save"), True),
            ("source.fresh-reload", lambda: self.source_case("reload"), True),
            ("imported.readonly", lambda: self.imported_source("read-only"), True),
            ("imported.open-source", lambda: self.imported_source("open-source"), True),
            ("rename.simple", lambda: self.rename_state_case("simple"), True),
            ("rename.composite", lambda: self.rename_state_case("composite"), True),
            ("rename.unicode-crlf", lambda: self.rename_state_case("unicode-crlf"), True),
            ("diagnostics.syntax", self.diagnostics, True),
            ("diagnostics.assembly", self.diagnostics_model, True),
            ("diagnostics.inspect", self.diagnostics_inspect, True),
            ("diagnostics.locate", self.diagnostics_locate, True),
            ("diagnostics.filter-search", self.diagnostics_filter_search, True),
            ("diagnostics.conflict-warning", self.diagnostics_conflict, True),
            ("diagnostics.suggested-fix", self.diagnostics_suggested_fix, True),
            ("keyboard.workspace", self.keyboard_workspace, True),
            ("graph.refresh", self.graph_smetana_semantics, True),
            ("graph.fit", lambda: self.graph_interaction("fit"), True),
            ("graph.zoom", lambda: self.graph_interaction("actual"), True),
            ("graph.selection", self.graph_selection, True),
            ("graph.reset", lambda: self.graph_interaction("reset"), True),
            ("simulation.initialize", self.simulation_initialize, True),
            ("simulation.step", self.simulation_cycle, True),
            ("simulation.run", self.simulation_continuous, True),
            ("simulation.pause", self.simulation_pause, True),
            ("simulation.continue", self.simulation_continue, True),
            ("simulation.reset", self.simulation_reset, True),
            ("simulation.stop", self.simulation_stop, True),
        ]
        for entity in (
            "state", "variable", "event", "transition", "guard", "effect", "lifecycle"
        ):
            for operation in ("add", "edit", "delete"):
                items.append(
                    (
                        "model.{}.{}".format(entity, operation),
                        lambda selected_entity=entity, selected_operation=operation: (
                            self.model_case(selected_entity, selected_operation)
                        ),
                        True,
                    )
                )
        for case_id in self.window_case_ids():
            items.append(
                (
                    "dynamic.case." + case_id,
                    lambda selected=case_id: self.dynamic_case(selected),
                    True,
                )
            )
        items.extend(
            [
                ("dynamic.mutation", lambda: self.dynamic_user_case(False), True),
                ("dynamic.recover", lambda: self.dynamic_user_case(True), True),
                ("dynamic.user", lambda: self.dynamic_user_case(False), True),
                ("dynamic.export", self.dynamic_export, True),
            ]
        )
        items.append(
            ("terminology.dynamic-not-formal", self.dynamic_terminology, True)
        )
        for kind in ("guard", "effect", "lifecycle", "numeric"):
            for validity in ("valid", "invalid"):
                items.append(
                    (
                        "formula.{}.{}".format(kind, validity),
                        lambda selected_kind=kind, selected_validity=validity: (
                            self.formula_case(selected_kind, selected_validity)
                        ),
                        True,
                    )
                )
        items.append(("formula.stale", self.formula_stale, True))
        for template_name in ("python", "c", "c_poll", "cpp", "cpp_poll"):
            items.append(
                (
                    "generation." + template_name.replace("_", "-"),
                    lambda selected=template_name: self.generation_template(selected),
                    True,
                )
            )
        items.extend(
            [
                ("generation.custom", self.generation_custom, True),
                ("generation.overwrite", self.generation_overwrite, True),
            ]
        )
        for kind in (
            "fcstm", "docx", "xlsx", "plantuml", "png", "svg", "pdf",
            "inspect-json", "dynamic-json",
        ):
            item_kind = {
                "fcstm": "dsl",
                "docx": "word",
                "xlsx": "excel",
            }.get(kind, kind)
            items.append(
                (
                    "export." + item_kind,
                    lambda selected=kind: self.export_kind(selected),
                    True,
                )
            )
        for kind in ("plantuml", "png", "svg", "pdf"):
            items.append(
                (
                    "graph.export." + kind,
                    lambda selected=kind: self.graph_export(selected),
                    True,
                )
            )
        items.extend(
            [
                ("tasks.copy", self.task_results, True),
                ("tasks.filter", self.task_filter, True),
                ("tasks.export", self.task_export_log, True),
                ("tasks.clear-filtered", self.task_clear_filtered, True),
                ("tasks.clear-completed", self.task_clear_completed, True),
                ("tasks.clear-all", self.task_clear_all, True),
                ("tasks.retry", self.task_retry, True),
                ("tasks.cancel", self.cancel_load, True),
                ("tasks.artifact", self.task_artifact, True),
                ("tasks.redaction", self.task_redaction, True),
                ("tasks.registry.load", lambda: self.task_registry("load"), True),
                ("tasks.registry.inspect", lambda: self.task_registry("inspect"), True),
                ("tasks.registry.graph", lambda: self.task_registry("graph"), True),
                ("tasks.registry.simulation", lambda: self.task_registry("simulation"), True),
                ("tasks.registry.dynamic", lambda: self.task_registry("dynamic"), True),
                ("tasks.registry.generation", lambda: self.task_registry("generation"), True),
                ("tasks.registry.export", lambda: self.task_registry("export"), True),
                (
                    "tasks.transient.document-validation",
                    lambda: self.task_transient("document-validation"),
                    True,
                ),
                (
                    "tasks.transient.formula-validation",
                    lambda: self.task_transient("formula-validation"),
                    True,
                ),
                ("cancel.load", self.cancel_load, True),
                ("cancel.simulation", self.simulation_stop, True),
                ("cancel.dynamic", self.cancel_dynamic, True),
                ("cancel.graph", self.cancel_graph, True),
                ("cancel.generation", self.cancel_generation, True),
                ("cancel.export", self.cancel_export, True),
                ("stale.graph", lambda: self.stale_task("graph"), True),
                ("stale.simulation", lambda: self.stale_task("simulation"), True),
                ("stale.dynamic", lambda: self.stale_task("dynamic"), True),
                ("stale.generation", lambda: self.stale_task("generation"), True),
                ("stale.export", lambda: self.stale_task("export"), True),
                ("keyboard.model", self.keyboard_model, True),
                ("keyboard.inspect", lambda: self.keyboard_case("inspect"), True),
                ("keyboard.generation", lambda: self.keyboard_case("generation"), True),
                ("keyboard.templates", lambda: self.keyboard_case("templates"), True),
                ("keyboard.graph", lambda: self.keyboard_case("graph"), True),
                ("keyboard.simulation", lambda: self.keyboard_case("simulation"), True),
                ("keyboard.syntax", lambda: self.keyboard_case("syntax"), True),
                ("keyboard.formula.guard", lambda: self.keyboard_case("formula.guard"), True),
                ("keyboard.formula.effect", lambda: self.keyboard_case("formula.effect"), True),
                ("keyboard.formula.lifecycle", lambda: self.keyboard_case("formula.lifecycle"), True),
                ("keyboard.formula.numeric", lambda: self.keyboard_case("formula.numeric"), True),
                ("graph.drag", self.graph_drag, True),
                (
                    "export.overwrite-preserves-target",
                    self.failure_recovery,
                    True,
                ),
                ("geometry.active-workspaces", self.geometry_active_workspaces, True),
            ]
        )
        for name, function, with_document in items:
            self.run_item(name, function, with_document=with_document)
        return self.results

    @staticmethod
    def window_case_ids():
        return (
            "design_evented_pseudo_chain_invalid_then_valid",
            "design_validation_failure_multilevel_transition",
            "expression_failure_transition_guard_raises_expression_error",
            "pseudo_self_loop_step_limit_raises_dfs_error",
        )

    def _workspace_specs(self):
        return (
            (self.window.action_show_model, self.window.model_workspace, "tree_all_state"),
            (self.window.action_show_source, self.window.source_workspace, "source_editor"),
            (self.window.action_show_graph, self.window.graph_workspace, "graph_refresh_button"),
            (
                self.window.action_show_diagnostics,
                self.window.diagnostics_workspace,
                "diagnostics_table",
            ),
            (
                self.window.action_show_simulation,
                self.window.simulation_workspace,
                "simulation_initialize_button",
            ),
            (
                self.window.action_show_dynamic_validation,
                self.window.dynamic_validation_workspace,
                "dynamic_case_combo",
            ),
        )

    def _activate_workspace_shortcut(self, action, page, focus_name):
        before = self.app.focusWidget()
        self.window.raise_()
        self.window.activateWindow()
        receiver = self.window

        def activate_receiver():
            self.window.raise_()
            self.window.activateWindow()
            receiver.setFocus(QtCore.Qt.ActiveWindowFocusReason)
            self.app.processEvents()
            return self.window.isActiveWindow() and receiver.hasFocus()

        self._wait_until(
            activate_receiver,
            timeout_ms=15000,
        )
        QtTest.QTest.keySequence(receiver, action.shortcut())
        self._wait_until(
            lambda: self.window.workspace_tabs.currentWidget() is page,
            timeout_ms=5000,
        )
        target = self.window.findChild(QtWidgets.QWidget, focus_name)
        if target is None or not target.isVisibleTo(self.window):
            raise RuntimeError(focus_name + " is not visible after workspace shortcut")
        if not target.hasFocus():
            raise RuntimeError(focus_name + " did not receive focus")
        return {
            "action": action.objectName(),
            "shortcut": action.shortcut().toString(),
            "focus_before": "" if before is None else before.objectName(),
            "focus_after": target.objectName(),
            "page": page.objectName(),
        }

    @staticmethod
    def _keyboard_text(widget, value):
        widget.setFocus(QtCore.Qt.TabFocusReason)
        QtTest.QTest.keySequence(widget, QtGui.QKeySequence.SelectAll)
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Backspace)
        QtTest.QTest.keyClicks(widget, str(value))

    def _wait_until(self, predicate, timeout_ms=3000):
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QtTest.QTest.qWait(10)
        raise TimeoutError("GUI state did not become ready within {} ms".format(timeout_ms))

    def document_open(self):
        def open_through_dialog():
            _schedule_file_dialog_path(self.source_path)
            QtTest.QTest.keySequence(
                self.window, self.window.action_import_state_machine.shortcut()
            )

        _wait_signal(
            self.window.document_load_finished,
            open_through_dialog,
        )
        session = self.window.document_session
        if session is None or session.current_valid_snapshot is None:
            raise RuntimeError("keyboard open did not install a valid document")
        if self.window.source_editor.toPlainText() != _SOURCE:
            raise RuntimeError("opened source text differs from file bytes")
        self.artifacts.append(
            _screenshot(self.window, self.artifact_dir, "01-open-{}x{}".format(*self.viewport))
        )
        return "opened revision {} through Ctrl+O".format(session.source_revision)

    def recent_reopen(self):
        before = self.window.document_session
        entries = [
            action
            for action in self.window.menu_recent_files.actions()
            if action.property("recent_path")
        ]
        if not entries:
            raise RuntimeError("recent-files menu has no document entry")
        target_action = entries[0]
        target_action_name = target_action.objectName()
        target_tooltip = target_action.toolTip()
        _wait_signal(self.window.document_load_finished, target_action.trigger)
        after = self.window.document_session
        if after is None or after.session_id == before.session_id:
            raise RuntimeError("recent-file menu did not create a fresh document session")
        if Path(after.path).resolve() != self.source_path.resolve():
            raise RuntimeError("recent-file menu reopened the wrong path")
        if after.source_text != before.source_text:
            raise RuntimeError("recent-file reopen changed source text")
        self._current_evidence = {
            "action": target_action_name,
            "menu": self.window.menu_recent_files.objectName(),
            "path_redacted": target_tooltip,
            "session_changed": True,
            "source_revision": after.source_revision,
        }
        return "reopened the current fixture through File > Recent Files"

    def document_cancel_load(self):
        before = self.window.document_session
        _schedule_file_dialog_cancel()
        QtTest.QTest.keySequence(
            self.window, self.window.action_import_state_machine.shortcut()
        )
        self.app.processEvents()
        if self.window.document_session is not before:
            raise RuntimeError("cancelling the file dialog replaced the session")
        if self.window.task_center.records:
            raise RuntimeError("cancelled file selection registered a load task")
        self._current_evidence = {
            "session_preserved": True,
            "task_count": 0,
        }
        return "cancelled the real file dialog without starting a load"

    def document_failed_load_preserves_session(self):
        failed_path = self.source_path.parent / "removed-after-selection.fcstm"
        failed_path.write_text(_SOURCE, encoding="utf-8")
        before_session = self.window.document_session
        before_manager = self.window.state_manager
        before_text = self.window.source_editor.toPlainText()
        before_revision = before_session.source_revision
        before_workspace = self.window.workspace_tabs.currentIndex()

        def open_removed_document():
            _schedule_file_dialog_path(failed_path, remove_after_accept=True)
            _schedule_message_box_choice(QtWidgets.QMessageBox.Ok)
            QtTest.QTest.keySequence(
                self.window, self.window.action_import_state_machine.shortcut()
            )

        outcome = _wait_signal(
            self.window.document_load_finished,
            open_removed_document,
            timeout_ms=10000,
        )[0]
        if outcome.status.value != "failed":
            raise RuntimeError(
                "missing-file load did not report failed: "
                + outcome.status.value
            )
        if self.window.document_session is not before_session:
            raise RuntimeError("failed load replaced the active document session")
        if self.window.state_manager is not before_manager:
            raise RuntimeError("failed load replaced the active state manager")
        if self.window.source_editor.toPlainText() != before_text:
            raise RuntimeError("failed load replaced the visible source text")
        if self.window.document_session.source_revision != before_revision:
            raise RuntimeError("failed load changed the active source revision")
        if self.window.workspace_tabs.currentIndex() != before_workspace:
            raise RuntimeError("failed load changed the active workspace")
        self._current_evidence = {
            "selected_file": failed_path.name,
            "removed_after_dialog_accept": not failed_path.exists(),
            "logical_status": outcome.status.value,
            "session_preserved": True,
            "manager_preserved": True,
            "source_revision": before_revision,
            "workspace_index": before_workspace,
            "error_type": (
                None if outcome.error is None else type(outcome.error).__name__
            ),
        }
        return "preserved the active session after a real post-selection I/O failure"

    def dirty_replacement(self, choice):
        editor = self.window.source_editor
        editor.moveCursor(QtGui.QTextCursor.End)
        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return),
            accept=self._is_current_validation,
        )
        dirty_text = editor.toPlainText()
        before = self.window.document_session
        replacement = self.source_path.parent / "replacement.fcstm"
        replacement.write_text("state Replacement;", encoding="utf-8")
        choices = {
            "save": QtWidgets.QMessageBox.Save,
            "discard": QtWidgets.QMessageBox.Discard,
            "cancel": QtWidgets.QMessageBox.Cancel,
        }

        def trigger_replacement():
            _schedule_file_dialog_path(replacement)
            _schedule_message_box_choice(choices[choice])
            QtTest.QTest.keySequence(
                self.window, self.window.action_import_state_machine.shortcut()
            )

        if choice == "cancel":
            trigger_replacement()
            self.app.processEvents()
            if self.window.document_session is not before:
                raise RuntimeError("dirty Cancel replaced the session")
            if not self.window.document_session.dirty:
                raise RuntimeError("dirty Cancel cleared dirty state")
        else:
            _wait_signal(self.window.document_load_finished, trigger_replacement)
            if self.window.document_session is before:
                raise RuntimeError("dirty {} did not load replacement".format(choice))
            disk_text = self.source_path.read_text(encoding="utf-8")
            if choice == "save" and disk_text != dirty_text:
                raise RuntimeError("dirty Save did not persist exact text")
            if choice == "discard" and disk_text != _SOURCE:
                raise RuntimeError("dirty Discard modified the original file")
        self._current_evidence = {
            "choice": choice,
            "original_saved": self.source_path.read_text(encoding="utf-8") == dirty_text,
            "session_preserved": self.window.document_session is before,
        }
        return "completed dirty {} replacement branch".format(choice)

    def model_edit(self):
        editor = self.window.source_editor
        self._activate_workspace_shortcut(
            self.window.action_show_source,
            self.window.source_workspace,
            "source_editor",
        )
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

    def source_case(self, operation):
        editor = self.window.source_editor
        self._activate_workspace_shortcut(
            self.window.action_show_source,
            self.window.source_workspace,
            "source_editor",
        )
        editor.moveCursor(QtGui.QTextCursor.End)
        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return),
            accept=self._is_current_validation,
        )
        edited = editor.toPlainText()
        if edited != _SOURCE + "\n":
            raise RuntimeError("source edit did not publish exact text")
        evidence = {
            "operation": operation,
            "edited_revision": self.window.document_session.source_revision,
        }
        if operation == "edit":
            self._current_evidence = evidence
            return "edited source through the focused editor"

        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keySequence(
                editor, self.window.action_undo.shortcut()
            ),
            accept=self._is_current_validation,
        )
        if editor.toPlainText() != _SOURCE:
            raise RuntimeError("source undo did not restore exact text")
        evidence["undo_revision"] = self.window.document_session.source_revision
        if operation == "undo":
            self._current_evidence = evidence
            return "undid a source edit through the keyboard action"

        if operation == "redo":
            _wait_signal(
                self.window.document_validation_finished,
                lambda: QtTest.QTest.keySequence(
                    editor, self.window.action_redo.shortcut()
                ),
                accept=self._is_current_validation,
            )
            if editor.toPlainText() != edited:
                raise RuntimeError("source redo did not restore exact text")
            evidence["redo_revision"] = self.window.document_session.source_revision
            self._current_evidence = evidence
            return "redid the source edit through the keyboard action"

        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keySequence(
                editor, self.window.action_redo.shortcut()
            ),
            accept=self._is_current_validation,
        )
        QtTest.QTest.keySequence(
            editor, self.window.action_save_state_machine.shortcut()
        )
        self.app.processEvents()
        if self.source_path.read_text(encoding="utf-8") != edited:
            raise RuntimeError("source save did not persist exact text")
        if self.window.document_session.dirty:
            raise RuntimeError("source save did not clear dirty state")
        evidence["saved_bytes"] = len(edited.encode("utf-8"))
        if operation == "save":
            self._current_evidence = evidence
            return "saved the edited source through the keyboard action"
        if operation != "reload":
            raise RuntimeError("unknown source operation: " + operation)

        before_session = self.window.document_session.session_id

        def reload_through_dialog():
            _schedule_file_dialog_path(self.source_path)
            QtTest.QTest.keySequence(
                self.window, self.window.action_import_state_machine.shortcut()
            )

        _wait_signal(self.window.document_load_finished, reload_through_dialog)
        if self.window.document_session.session_id == before_session:
            raise RuntimeError("source reload reused the previous session")
        if self.window.source_editor.toPlainText() != edited:
            raise RuntimeError("source reload changed persisted text")
        evidence["fresh_session"] = True
        self._current_evidence = evidence
        return "reloaded saved source through the file dialog"

    def source_save_fresh_reload(self):
        editor = self.window.source_editor
        self._activate_workspace_shortcut(
            self.window.action_show_source,
            self.window.source_workspace,
            "source_editor",
        )
        editor.moveCursor(QtGui.QTextCursor.End)
        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return),
            accept=self._is_current_validation,
        )
        expected = editor.toPlainText()
        QtTest.QTest.keySequence(
            editor, self.window.action_save_state_machine.shortcut()
        )
        self.app.processEvents()
        if self.source_path.read_text(encoding="utf-8") != expected:
            raise RuntimeError("keyboard save did not write exact source text")
        if self.window.document_session.dirty:
            raise RuntimeError("keyboard save did not clear dirty state")

        def reload_through_dialog():
            _schedule_file_dialog_path(self.source_path)
            QtTest.QTest.keySequence(
                self.window, self.window.action_import_state_machine.shortcut()
            )

        before_session = self.window.document_session.session_id
        _wait_signal(self.window.document_load_finished, reload_through_dialog)
        if self.window.document_session.session_id == before_session:
            raise RuntimeError("fresh reload reused the old document session")
        if self.window.source_editor.toPlainText() != expected:
            raise RuntimeError("fresh reload did not preserve saved source")
        self._current_evidence = {
            "saved_bytes": len(expected.encode("utf-8")),
            "fresh_session": True,
            "dirty": self.window.document_session.dirty,
        }
        return "saved exact source and reloaded it through the file dialog"

    def imported_source(self, operation):
        child = self.source_path.parent / "child.fcstm"
        child.write_text(
            "state Child { event Go; state A; state B; [*] -> A; A -> B : Go; }",
            encoding="utf-8",
        )
        source = (
            'state Root { import "./child.fcstm" as Imported; '
            "[*] -> Imported; Imported -> [*]; }"
        )
        _wait_signal(
            self.window.document_validation_finished,
            lambda: _keyboard_replace(self.window.source_editor, source),
            accept=self._is_current_validation,
        )
        items = self.window.tree_all_state.findItems(
            "Imported", QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
        )
        if len(items) != 1:
            raise RuntimeError("imported state projection is missing")
        item = items[0]
        rect = self.window.tree_all_state.visualItemRect(item)
        QtTest.QTest.mouseClick(
            self.window.tree_all_state.viewport(),
            QtCore.Qt.LeftButton,
            pos=rect.center(),
        )
        if self.window.event_edit_button.isEnabled() or self.window.event_delete_button.isEnabled():
            raise RuntimeError("imported event edit controls are not read-only")
        if not self.window.event_open_source_button.isEnabled():
            raise RuntimeError("imported source navigation is unavailable")
        if operation == "read-only":
            self._current_evidence = {
                "read_only": True,
                "edit_enabled": self.window.event_edit_button.isEnabled(),
                "delete_enabled": self.window.event_delete_button.isEnabled(),
            }
            return "kept imported model content read-only"
        if operation != "open-source":
            raise RuntimeError("unknown imported-source operation: " + operation)
        _press(self.window.event_open_source_button)
        page = self.window.workspace_tabs.currentWidget()
        expected_uri = SourceDocument.from_file(child).uri
        if page.property("source_uri") != expected_uri:
            raise RuntimeError("imported source navigation opened the wrong canonical URI")
        self._current_evidence = {
            "read_only": True,
            "source_uri": expected_uri,
            "workspace": page.objectName(),
        }
        return "kept imported content read-only and opened its physical source"

    def rename_state_case(self, variant):
        if variant == "simple":
            old_name, new_name = "Idle", "Ready"
            original = _SOURCE
        elif variant == "composite":
            old_name, new_name = "Group", "Cluster"
            original = (
                "state Root { state Group { state Child; [*] -> Child; "
                "Child -> [*]; } [*] -> Group; Group -> [*]; }"
            )
        elif variant == "unicode-crlf":
            old_name, new_name = "Idle", "Ready"
            original = ("// 中文注释\n" + _SOURCE).replace("\n", "\r\n")
        else:
            raise RuntimeError("unknown rename variant: " + variant)
        if original != _SOURCE:
            self.source_path.write_bytes(original.encode("utf-8"))
            session = self.window.document_service.load(self.source_path)
            self.window._set_active_document_session(session)
            self.app.processEvents()
        items = self.window.tree_all_state.findItems(
            old_name, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
        )
        if len(items) != 1:
            raise RuntimeError("rename target is missing: " + old_name)
        item = items[0]
        rect = self.window.tree_all_state.visualItemRect(item)
        QtTest.QTest.mouseClick(
            self.window.tree_all_state.viewport(),
            QtCore.Qt.LeftButton,
            pos=rect.center(),
        )
        before_revision = self.window.document_session.source_revision
        _schedule_state_rename_dialog(new_name)
        viewport = self.window.tree_all_state.viewport()
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse,
            rect.center(),
            viewport.mapToGlobal(rect.center()),
        )
        QtWidgets.QApplication.postEvent(viewport, event)
        self.app.processEvents()
        self._wait_until(
            lambda: self.window.document_session.source_revision > before_revision,
            timeout_ms=5000,
        )
        changed = self.window.document_session.source_text
        if new_name not in changed or old_name in changed:
            raise RuntimeError("rename did not update exact state tokens")
        if variant == "unicode-crlf" and "\r\n" not in changed:
            raise RuntimeError("Unicode rename did not preserve CRLF source text")
        if variant == "unicode-crlf" and "// 中文注释" not in changed:
            raise RuntimeError("rename changed surrounding Unicode text")
        self._current_evidence = {
            "variant": variant,
            "old_name": old_name,
            "new_name": new_name,
            "crlf_preserved": variant != "unicode-crlf" or "\r\n" in changed,
            "revision": self.window.document_session.source_revision,
        }
        return "renamed {} state through tree context menu".format(variant)

    def _load_model_fixture(self, source):
        self.source_path.write_text(source, encoding="utf-8")
        session = self.window.document_service.load(self.source_path)
        self.window._set_active_document_session(session)
        self.app.processEvents()

    def _select_tree_text(self, text):
        items = self.window.tree_all_state.findItems(
            text, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
        )
        if len(items) != 1:
            raise RuntimeError("model tree item is missing: " + text)
        item = items[0]
        rect = self.window.tree_all_state.visualItemRect(item)
        QtTest.QTest.mouseClick(
            self.window.tree_all_state.viewport(),
            QtCore.Qt.LeftButton,
            pos=rect.center(),
        )
        return item, rect

    def _post_context_menu(self, widget, point):
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse,
            point,
            widget.mapToGlobal(point),
        )
        QtWidgets.QApplication.postEvent(widget, event)
        self.app.processEvents()

    def model_case(self, entity, operation):
        before_revision = self.window.document_session.source_revision
        if entity == "state":
            self._select_tree_text("Root")
            if operation == "add":
                _schedule_state_name_dialog("Added")
                _press(self.window.button_add_state)
                expected, absent = "state Added;", None
            elif operation == "edit":
                return self.rename_state_case("simple")
            else:
                self._load_model_fixture(
                    "state Root { state A; state B; [*] -> A; A -> [*]; B -> [*]; }"
                )
                before_revision = self.window.document_session.source_revision
                _item, rect = self._select_tree_text("B")
                _schedule_menu_action(2, QtWidgets.QMessageBox.Yes)
                self._post_context_menu(self.window.tree_all_state.viewport(), rect.center())
                expected, absent = None, "state B;"
        elif entity == "variable":
            self._load_model_fixture(
                "def int value = 1;\nstate Root { state A; [*] -> A; A -> [*]; }"
            )
            before_revision = self.window.document_session.source_revision
            field = self.window.edit_var_def
            values = {
                "add": "def int value = 1;\ndef int extra = 2;",
                "edit": "def int value = 3;",
                "delete": "",
            }
            if operation == "delete":
                self._keyboard_text(field, "")
            else:
                _keyboard_replace(field, values[operation])
            expected = None if operation == "delete" else values[operation].splitlines()[-1]
            absent = "def int value" if operation == "delete" else None
        elif entity == "event":
            source = (
                "state Root { event Go named \"Go\"; state A; state B; "
                "[*] -> A; A -> B : Go; B -> [*]; }"
            )
            if operation == "add":
                source = "state Root { state A; [*] -> A; A -> [*]; }"
            self._load_model_fixture(source)
            before_revision = self.window.document_session.source_revision
            self._select_tree_text("Root")
            if operation == "add":
                _schedule_event_editor("Added", "Added Event")
                _schedule_preview_accept()
                _press(self.window.event_add_button)
                expected, absent = "event Added", None
            elif operation == "edit":
                self.window.event_table.selectRow(0)
                _schedule_event_editor("Run", "Run Event")
                _schedule_preview_accept()
                _press(self.window.event_edit_button)
                expected, absent = "event Run", "event Go"
            else:
                self.window.event_table.selectRow(0)
                _schedule_message_box_choice(QtWidgets.QMessageBox.Yes)
                _schedule_preview_accept()
                _press(self.window.event_delete_button)
                expected, absent = None, "event Go"
        elif entity in ("transition", "guard", "effect"):
            base_transition = "A -> B"
            if entity == "guard" and operation != "add":
                base_transition += " : if [count >= 0]"
            if entity == "effect" and operation != "add":
                base_transition += " effect { count = count + 1; }"
            source = (
                "def int count = 0;\nstate Root { state A; state B; [*] -> A; "
                + base_transition
                + "; B -> [*]; }"
            )
            if entity == "transition" and operation == "add":
                source = (
                    "def int count = 0;\nstate Root { state A; state B; "
                    "[*] -> A; B -> [*]; }"
                )
            self._load_model_fixture(source)
            before_revision = self.window.document_session.source_revision
            self._select_tree_text("Root")
            if operation == "add" and entity == "transition":
                _schedule_transition_dialog(
                    "A", "B", "count >= 0", "count = count + 1;"
                )
                _press(self.window.button_transition)
                expected, absent = "A -> B", None
            else:
                row = next(
                    row
                    for row in range(self.window.table_transition.rowCount())
                    if self.window.table_transition.item(row, 0).text() == "A"
                )
                self.window.table_transition.selectRow(row)
                rect = self.window.table_transition.visualItemRect(
                    self.window.table_transition.item(row, 0)
                )
                if operation == "delete" and entity == "transition":
                    _schedule_menu_action(1, QtWidgets.QMessageBox.Yes)
                    expected, absent = None, "A -> B"
                else:
                    _schedule_menu_action(0)
                    condition = ""
                    action = ""
                    if entity == "transition":
                        condition = "count >= 0"
                        action = "count = count + 1;"
                        expected = "count >= 0"
                    if entity == "guard":
                        action = "count = count + 1;"
                        condition = {
                            "add": "count >= 0",
                            "edit": "count > 1",
                            "delete": "",
                        }[operation]
                    if entity == "effect":
                        condition = "count >= 0"
                        action = {
                            "add": "count = count + 1;",
                            "edit": "count = count + 2;",
                            "delete": "",
                        }[operation]
                    if entity == "transition":
                        expected = condition
                    elif entity == "guard" and operation != "delete":
                        expected = condition
                    elif entity == "effect" and operation != "delete":
                        expected = action.rstrip(";")
                    else:
                        expected = None
                    absent = (
                        "if [count >= 0]" if entity == "guard" and operation == "delete"
                        else "count = count + 1" if entity == "effect" and operation == "delete"
                        else None
                    )
                    _schedule_transition_dialog("A", "B", condition, action)
                self._post_context_menu(
                    self.window.table_transition.viewport(), rect.center()
                )
        elif entity == "lifecycle":
            lifecycle = " enter { count = count + 1; }" if operation != "add" else ""
            source = (
                "def int count = 0;\nstate Root {"
                + lifecycle
                + " state A; [*] -> A; A -> [*]; }"
            )
            self._load_model_fixture(source)
            before_revision = self.window.document_session.source_revision
            self._select_tree_text("Root")
            if operation == "add":
                _schedule_lifecycle_dialog("count = count + 1;")
                _press(self.window.button_lifecycle)
                expected, absent = "count = count + 1", None
            else:
                self.window.table_lifecycle.selectRow(0)
                rect = self.window.table_lifecycle.visualItemRect(
                    self.window.table_lifecycle.item(0, 0)
                )
                if operation == "edit":
                    _schedule_menu_action(0)
                    _schedule_lifecycle_dialog("count = count + 2;")
                    expected, absent = "count = count + 2", "count = count + 1"
                else:
                    _schedule_menu_action(1, QtWidgets.QMessageBox.Yes)
                    expected, absent = None, "enter {"
                self._post_context_menu(
                    self.window.table_lifecycle.viewport(), rect.center()
                )
        else:
            raise RuntimeError("unknown model entity: " + entity)
        self._wait_until(
            lambda: self.window.document_session.source_revision > before_revision,
            timeout_ms=5000,
        )
        changed = self.window.document_session.source_text
        if expected is not None and expected not in changed:
            raise RuntimeError("model {} {} did not publish expected source".format(entity, operation))
        if absent is not None and absent in changed:
            raise RuntimeError("model {} {} retained removed source".format(entity, operation))
        self._current_evidence = {
            "entity": entity,
            "operation": operation,
            "revision_before": before_revision,
            "revision_after": self.window.document_session.source_revision,
            "expected": expected,
            "absent": absent,
        }
        return "completed model {} {} through its form".format(entity, operation)

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
            _screenshot(
                self.window,
                self.artifact_dir,
                "02-diagnostics-{}-{}x{}".format(
                    self._case_name, *self.viewport
                ),
            )
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

    def _diagnostic_source_case(self, source, expected_state, source_kind):
        editor = self.window.source_editor
        _wait_signal(
            self.window.document_validation_finished,
            lambda: _keyboard_replace(editor, source),
            accept=self._is_current_validation,
        )
        if self.window.document_session.validation_state is not expected_state:
            raise RuntimeError(source_kind + " diagnostic state is incorrect")
        self._activate_workspace_shortcut(
            self.window.action_show_diagnostics,
            self.window.diagnostics_workspace,
            "diagnostics_table",
        )
        panel = self.window.diagnostics_panel
        sources = {
            panel.table.item(row, panel.COLUMN_SOURCE).text()
            for row in range(panel.table.rowCount())
        }
        if source_kind not in sources:
            raise RuntimeError(source_kind + " diagnostic provenance is missing")
        self._current_evidence = {
            "source_kind": source_kind,
            "diagnostic_count": panel.table.rowCount(),
            "sources": sorted(sources),
        }
        return "displayed {} diagnostics with preserved provenance".format(source_kind)

    def diagnostics_model(self):
        return self._diagnostic_source_case(
            "state Root { state A; state A; }",
            ValidationState.INVALID_MODEL,
            "model",
        )

    def diagnostics_locate(self):
        detail = self.diagnostics()
        self._current_evidence["independent_item"] = "locate"
        return detail

    def diagnostics_inspect(self):
        return self._diagnostic_source_case(
            "state Root;",
            ValidationState.VALID_WITH_WARNINGS,
            "inspect",
        )

    def diagnostics_filter_search(self):
        self.diagnostics_conflict()
        panel = self.window.diagnostics_panel
        _select_combo_data(panel.severity_filter, "warning")
        _keyboard_replace(panel.search_edit, "W_REDUNDANT_TRANSITION")
        self.app.processEvents()
        if panel.table.rowCount() != 1:
            raise RuntimeError("diagnostic warning/code filters are not conjunctive")
        if panel.table.item(0, panel.COLUMN_CODE).text() != "W_REDUNDANT_TRANSITION":
            raise RuntimeError("diagnostic search returned the wrong code")
        self._current_evidence = {
            "severity": "warning",
            "search": "W_REDUNDANT_TRANSITION",
            "rows": 1,
        }
        return "filtered and searched structured diagnostics"

    def diagnostics_conflict(self):
        source = (
            "state Root { state A; state B; [*] -> A; "
            "A -> B; A -> B; }"
        )
        self._diagnostic_source_case(
            source, ValidationState.VALID_WITH_WARNINGS, "inspect"
        )
        panel = self.window.diagnostics_panel
        codes = {
            panel.table.item(row, panel.COLUMN_CODE).text()
            for row in range(panel.table.rowCount())
        }
        if "W_REDUNDANT_TRANSITION" not in codes:
            raise RuntimeError("conflicting transitions produced no warning")
        self._current_evidence = {
            "code": "W_REDUNDANT_TRANSITION",
            "codes": sorted(codes),
        }
        return "displayed a redundant-transition conflict warning"

    def diagnostics_suggested_fix(self):
        source = "state Root { state A; [*] -> A; }"
        self._diagnostic_source_case(
            source, ValidationState.VALID_WITH_WARNINGS, "inspect"
        )
        panel = self.window.diagnostics_panel
        row = next(
            index
            for index in range(panel.table.rowCount())
            if panel.table.item(index, panel.COLUMN_CODE).text() == "W_DEADLOCK_LEAF"
        )
        panel.table.selectRow(row)
        self.app.processEvents()
        if not panel.suggested_fix_button.isVisibleTo(self.window):
            raise RuntimeError("materialized suggested fix action is not visible")
        before_revision = self.window.document_session.source_revision
        _schedule_message_box_choice(QtWidgets.QMessageBox.Yes)
        _press(panel.suggested_fix_button)
        self._wait_until(
            lambda: self.window.document_session.source_revision > before_revision,
            timeout_ms=5000,
        )
        changed = self.window.document_session.source_text
        if self.window.document_session.source_revision <= before_revision:
            raise RuntimeError("suggested fix did not advance source revision")
        if "A -> [*];" not in changed:
            raise RuntimeError("suggested fix did not materialize the expected transition")
        self._current_evidence = {
            "code": "W_DEADLOCK_LEAF",
            "revision_before": before_revision,
            "revision_after": self.window.document_session.source_revision,
        }
        return "previewed, confirmed, and revalidated a suggested fix"

    def keyboard_workspace(self):
        journeys = []
        for action, page, focus_name in self._workspace_specs():
            journeys.append(
                self._activate_workspace_shortcut(action, page, focus_name)
            )
        self._current_evidence = {"journeys": journeys}
        return "activated six workspaces through Ctrl/Cmd+1..6 with focus"

    def graph_smetana_semantics(self):
        journey = self._activate_workspace_shortcut(
            self.window.action_show_graph,
            self.window.graph_workspace,
            "graph_refresh_button",
        )
        result = _wait_signal(
            self.window.graph_task_finished,
            lambda: _press(self.window.graph_panel.refresh_button),
        )[0]
        if result.status.value != "success":
            raise RuntimeError(
                "graph refresh {}: {}".format(result.status.value, result.error)
            )
        graph = result.value.get("graph") if isinstance(result.value, dict) else None
        if (
            graph is None
            or graph.engine != "smetana"
            or graph.exit_code != 0
        ):
            raise RuntimeError("graph refresh omitted valid Smetana execution evidence")
        required_labels = {"Root", "Idle", "Running", "Start"}
        if not required_labels <= set(graph.semantic_labels):
            raise RuntimeError(
                "graph semantic labels incomplete: {}".format(
                    sorted(graph.semantic_labels)
                )
            )
        if graph.transition_count < 3 or not graph.semantic_svg_sha256:
            raise RuntimeError("graph source/SVG semantic binding is incomplete")
        transition_edges = [
            {
                "source": item.source,
                "target": item.target,
                "label": item.label,
            }
            for item in graph.semantic_transitions
        ]
        scene = self.window.graph_panel.view.scene()
        if scene is None or scene.sceneRect().isEmpty():
            raise RuntimeError("graph refresh produced no visible scene")
        self._current_evidence = {
            "journey": journey,
            "engine": graph.engine,
            "renderer": graph.renderer,
            "exit_code": graph.exit_code,
            "stderr": graph.stderr,
            "source_sha256": graph.source_sha256,
            "semantic_svg_sha256": graph.semantic_svg_sha256,
            "labels": list(graph.semantic_labels),
            "transitions": transition_edges,
        }
        return "Smetana graph rendered with labels {} and {} transitions".format(
            ",".join(sorted(required_labels)), graph.transition_count
        )

    def graph_interaction(self, action):
        self.graph_smetana_semantics()
        panel = self.window.graph_panel
        buttons = {
            "fit": panel.fit_button,
            "actual": panel.actual_button,
            "reset": panel.reset_button,
        }
        button = buttons[action]
        if not button.isEnabled():
            raise RuntimeError(action + " graph control is unavailable")
        before = panel.view.transform().m11()
        _press(button)
        self.app.processEvents()
        after = panel.view.transform().m11()
        if not after or after <= 0:
            raise RuntimeError(action + " produced an invalid graph transform")
        if action == "actual" and after != 1.0:
            raise RuntimeError("100% graph action did not reset scale")
        self._current_evidence.update(
            {"interaction": action, "scale_before": before, "scale_after": after}
        )
        return "executed graph {} control".format(action)

    def graph_selection(self):
        item, rect = self._select_tree_text("Idle")
        selected_path = "Root.Idle"
        if selected_path not in self.window.graph_panel.status_label.text():
            raise RuntimeError("tree selection was not propagated to the graph status")
        self._activate_workspace_shortcut(
            self.window.action_show_graph,
            self.window.graph_workspace,
            "graph_refresh_button",
        )
        if selected_path not in self.window.graph_panel.status_label.text():
            raise RuntimeError("graph workspace lost the selected state path")
        self._current_evidence = {
            "tree_item": item.text(0),
            "tree_rect": [rect.x(), rect.y(), rect.width(), rect.height()],
            "selected_path": selected_path,
            "graph_status": self.window.graph_panel.status_label.text(),
        }
        return "propagated a real model-tree selection into the graph workspace"

    def graph_export(self, kind):
        panel = self.window.graph_panel
        self._activate_workspace_shortcut(
            self.window.action_show_graph,
            self.window.graph_workspace,
            "graph_refresh_button",
        )
        suffix = "puml" if kind == "plantuml" else kind
        target = self.artifact_dir / "graph-exports" / (
            self._case_name + "." + suffix
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        panel.export_combo.setFocus(QtCore.Qt.TabFocusReason)
        QtTest.QTest.keyClick(panel.export_combo, QtCore.Qt.Key_Home)
        index = panel.export_combo.findText(kind)
        for _unused in range(index):
            QtTest.QTest.keyClick(panel.export_combo, QtCore.Qt.Key_Down)

        def export_through_dialog():
            _schedule_file_dialog_path(target)
            _press(panel.export_button)

        result = _wait_signal(
            self.window.graph_task_finished,
            export_through_dialog,
            timeout_ms=30000,
        )[0]
        if result.status.value != "success" or not target.is_file():
            raise RuntimeError(kind + " graph export failed")
        data = target.read_bytes()
        signatures = {
            "plantuml": b"@startuml",
            "png": b"\x89PNG\r\n\x1a\n",
            "svg": b"<svg",
            "pdf": b"%PDF",
        }
        if signatures[kind] not in data[:4096]:
            raise RuntimeError(kind + " graph export has invalid magic/content")
        artifact = _artifact(target, self.artifact_dir)
        self.artifacts.append(artifact)
        self._current_evidence = {
            "kind": kind,
            "size": artifact["size"],
            "sha256": artifact["sha256"],
        }
        return "exported graph " + kind

    def _is_current_validation(self, result):
        session = self.window.document_session
        return bool(
            session is not None
            and result.stamp.session_id == session.session_id
            and result.stamp.source_revision == session.source_revision
        )

    def simulation(self):
        panel = self.window.simulation_panel
        journey = self._activate_workspace_shortcut(
            self.window.action_show_simulation,
            self.window.simulation_workspace,
            "simulation_initialize_button",
        )
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.initialize_button),
        )
        self._keyboard_text(panel.event_edit, "Start")
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.cycle_button),
        )
        if panel.transcript_table.rowCount() < 2 or "Root.Running" not in panel.snapshot_label.text():
            raise RuntimeError("ordinary simulation transcript/state is incomplete")
        self._current_evidence = {
            "journey": journey,
            "runtime_initialized": self.window._simulation_session is not None,
            "cycle": self.window._simulation_session.snapshot().cycle,
            "state": list(self.window._simulation_session.snapshot().state_path),
        }
        return "initialized and advanced real SimulationRuntime"

    def _initialize_simulation_case(self):
        panel = self.window.simulation_panel
        self._activate_workspace_shortcut(
            self.window.action_show_simulation,
            self.window.simulation_workspace,
            "simulation_initialize_button",
        )
        result = _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.initialize_button),
        )[0]
        if result.status.value != "success" or self.window._simulation_session is None:
            raise RuntimeError("ordinary simulation initialization failed")
        return panel, self.window._simulation_session

    def simulation_initialize(self):
        panel, session = self._initialize_simulation_case()
        snapshot = session.snapshot()
        if panel.transcript_table.rowCount() < 1 or snapshot.cycle < 1:
            raise RuntimeError("initialization did not publish its initial cycle")
        self._current_evidence = {
            "runtime_id": id(session.runtime),
            "cycle": snapshot.cycle,
            "state": list(snapshot.state_path),
        }
        return "initialized a real SimulationRuntime"

    def simulation_cycle(self):
        panel, session = self._initialize_simulation_case()
        before = session.snapshot().cycle
        self._keyboard_text(panel.event_edit, "Start")
        result = _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.cycle_button),
        )[0]
        after = session.snapshot()
        if result.status.value != "success" or after.cycle != before + 1:
            raise RuntimeError("single-cycle simulation did not advance exactly once")
        if tuple(after.state_path) != ("Root", "Running"):
            raise RuntimeError("Start did not drive the expected transition")
        self._current_evidence = {
            "before_cycle": before,
            "after_cycle": after.cycle,
            "state": list(after.state_path),
        }
        return "advanced one event-driven cycle"

    def simulation_continuous(self):
        panel, session = self._initialize_simulation_case()
        before = session.snapshot().cycle
        self._keyboard_text(panel.event_edit, "")
        self._keyboard_text(panel.cycle_count, "2")
        QtTest.QTest.keyClick(panel.cycle_count, QtCore.Qt.Key_Enter)
        result = _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.run_button),
        )[0]
        if result.status.value != "success" or len(result.value.cycles) != 2:
            raise RuntimeError("continuous simulation did not execute two cycles")
        self._current_evidence = {
            "before_cycle": before,
            "after_cycle": session.snapshot().cycle,
            "segment_cycles": len(result.value.cycles),
        }
        return "ran a two-cycle continuous segment"

    def simulation_pause(self):
        return self.simulation_pause_continue(continue_run=False)

    def simulation_continue(self):
        return self.simulation_pause_continue(continue_run=True)

    def simulation_pause_continue(self, continue_run=True):
        panel = self.window.simulation_panel
        journey = self._activate_workspace_shortcut(
            self.window.action_show_simulation,
            self.window.simulation_workspace,
            "simulation_initialize_button",
        )
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.initialize_button),
        )
        self._keyboard_text(panel.event_edit, "Start")
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.cycle_button),
        )
        session = self.window._simulation_session
        if session is None or "Root.Running" not in panel.snapshot_label.text():
            raise RuntimeError("ordinary simulation did not reach Running")
        runtime = session.runtime
        before_cycle = session.snapshot().cycle
        before_rows = panel.transcript_table.rowCount()
        self._keyboard_text(panel.event_edit, "")
        if panel.event_values():
            raise RuntimeError("continuous simulation events were not cleared")
        self._keyboard_text(panel.cycle_count, "10000")
        QtTest.QTest.keyClick(panel.cycle_count, QtCore.Qt.Key_Enter)
        if panel.cycle_count.value() != 10000:
            raise RuntimeError(
                "continuous cycle count was not committed: {}".format(
                    panel.cycle_count.value()
                )
            )

        def start_and_pause():
            _press(panel.run_button)
            self._wait_until(
                lambda: (
                    panel.pause_button.isEnabled()
                    and session.snapshot().cycle > before_cycle
                ),
                timeout_ms=5000,
            )
            _press(panel.pause_button)

        paused_result = _wait_signal(
            self.window.simulation_task_finished,
            start_and_pause,
            timeout_ms=20000,
        )[0]
        if not paused_result.value.paused:
            raise RuntimeError(
                "continuous simulation did not stop at a pause boundary "
                "(completed cycles: {})".format(len(paused_result.value.cycles))
            )
        if self.window._simulation_session.runtime is not runtime:
            raise RuntimeError("pause replaced the SimulationRuntime")
        if panel.status_label.text() != "已暂停" or panel.run_button.text() != "继续运行":
            raise RuntimeError("paused UI state is not visible")
        paused_cycle = session.snapshot().cycle
        if paused_cycle <= before_cycle or panel.transcript_table.rowCount() <= before_rows:
            raise RuntimeError("pause did not retain completed cycle evidence")

        if not continue_run:
            self._current_evidence = {
                "same_runtime": True,
                "before_cycle": before_cycle,
                "paused_cycle": paused_cycle,
                "paused_segment_cycles": len(paused_result.value.cycles),
            }
            return "paused the same runtime at a cycle boundary"
        self.artifacts.append(
            _screenshot(
                self.window,
                self.artifact_dir,
                "04-simulation-paused-{}-{}x{}".format(
                    self._case_name, *self.viewport
                ),
            )
        )

        self._keyboard_text(panel.cycle_count, "2")
        QtTest.QTest.keyClick(panel.cycle_count, QtCore.Qt.Key_Enter)
        if panel.cycle_count.value() != 2:
            raise RuntimeError(
                "continued cycle count was not committed: {}".format(
                    panel.cycle_count.value()
                )
            )
        continued_result = _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.run_button),
        )[0]
        if continued_result.value.paused or continued_result.value.cancelled:
            raise RuntimeError("continued simulation did not complete normally")
        if self.window._simulation_session.runtime is not runtime:
            raise RuntimeError("continue replaced the SimulationRuntime")
        after_cycle = session.snapshot().cycle
        if after_cycle <= paused_cycle:
            raise RuntimeError("continue did not advance the paused runtime")
        self._current_evidence = {
            "journey": journey,
            "same_runtime": True,
            "before_cycle": before_cycle,
            "paused_cycle": paused_cycle,
            "continued_cycle": after_cycle,
            "paused_segment_cycles": len(paused_result.value.cycles),
            "continued_segment_cycles": len(continued_result.value.cycles),
        }
        return "paused and continued the same runtime at cycle boundaries"

    def simulation_reset(self):
        panel, session = self._initialize_simulation_case()
        runtime = session.runtime
        self._keyboard_text(panel.event_edit, "Start")
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.cycle_button),
        )
        result = _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.reset_button),
        )[0]
        if result.status.value != "success" or session.runtime is runtime:
            raise RuntimeError("reset did not replace the runtime")
        self._current_evidence = {
            "runtime_replaced": True,
            "reset_cycle": session.snapshot().cycle,
        }
        return "reset to a fresh runtime"

    def simulation_stop(self):
        panel, session = self._initialize_simulation_case()
        self._keyboard_text(panel.event_edit, "")
        self._keyboard_text(panel.cycle_count, "10000")
        QtTest.QTest.keyClick(panel.cycle_count, QtCore.Qt.Key_Enter)

        def start_and_stop():
            _press(panel.run_button)
            if not panel.cancel_button.isEnabled():
                raise RuntimeError("continuous run did not expose stop")
            _press(panel.cancel_button)

        result = _wait_signal(
            self.window.simulation_task_finished,
            start_and_stop,
            timeout_ms=20000,
        )[0]
        value = result.value
        if result.status.value != "cancelled" and not getattr(value, "cancelled", False):
            raise RuntimeError("stop did not cancel at a cycle boundary")
        self._current_evidence = {
            "cycle": session.snapshot().cycle,
            "retained_cycles": 0 if value is None else len(value.cycles),
            "status": result.status.value,
        }
        return "stopped continuous simulation and retained partial evidence"

    def dynamic_validation(self):
        panel = self.window.dynamic_validation_panel
        self._activate_workspace_shortcut(
            self.window.action_show_dynamic_validation,
            self.window.dynamic_validation_workspace,
            "dynamic_case_combo",
        )
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

    def dynamic_case(self, case_id):
        panel = self.window.dynamic_validation_panel
        self._activate_workspace_shortcut(
            self.window.action_show_dynamic_validation,
            self.window.dynamic_validation_workspace,
            "dynamic_case_combo",
        )
        _select_combo_data(panel.case_combo, case_id)
        result = _wait_signal(
            self.window.dynamic_validation_finished,
            lambda: _press(panel.run_case_button),
        )[0]
        payload = json.loads(panel.report_json())
        report = payload["report"]
        if result.status.value != "success" or report["case_id"] != case_id:
            raise RuntimeError("dynamic case result does not match its selection")
        if report["status"] not in ("passed", "expected_exception_passed"):
            raise RuntimeError("dynamic case did not pass: " + report["status"])
        report_path = self.artifact_dir / ("dynamic-" + case_id + ".json")
        report_path.write_text(panel.report_json(), encoding="utf-8")
        self.artifacts.append(_artifact(report_path, self.artifact_dir))
        self._current_evidence = {
            "case_id": case_id,
            "status": report["status"],
            "steps": len(report["steps"]),
            "provenance_status": payload["provenance"]["status"],
        }
        return "ran packaged dynamic case " + case_id

    def dynamic_user_case(self, expected_match):
        panel = self.window.dynamic_validation_panel
        case_id = "acceptance_recovery" if expected_match else "acceptance_mutation"
        case_dir = self.source_path.parent
        model_path = case_dir / "dynamic-model.fcstm"
        model_path.write_text(_SOURCE, encoding="utf-8")
        scenario_path = case_dir / (case_id + ".json")
        expected_state = "Root.Idle" if expected_match else "Root.Wrong"
        scenario_path.write_text(
            json.dumps(
                {
                    "schema": "fcstm-gui.dynamic-validation-scenario",
                    "version": 1,
                    "case_id": case_id,
                    "model_file": model_path.name,
                    "initial": {"state": None, "variables": {}},
                    "steps": [
                        {
                            "events": [],
                            "commands": [],
                            "expected": {
                                "state": expected_state,
                                "variables": {"count": 0},
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self._activate_workspace_shortcut(
            self.window.action_show_dynamic_validation,
            self.window.dynamic_validation_workspace,
            "dynamic_case_combo",
        )
        _schedule_file_dialog_path(scenario_path)
        _press(panel.browse_button)
        if Path(panel.scenario_edit.text()).resolve() != scenario_path.resolve():
            raise RuntimeError("dynamic scenario dialog selected the wrong file")
        result = _wait_signal(
            self.window.dynamic_validation_finished,
            lambda: _press(panel.run_user_button),
        )[0]
        payload = json.loads(panel.report_json())
        expected_status = "passed" if expected_match else "mismatch"
        if result.status.value != "success" or payload["status"] != expected_status:
            raise RuntimeError(
                "dynamic user case expected {}, got {}".format(
                    expected_status, payload.get("status")
                )
            )
        self._current_evidence = {
            "case_id": case_id,
            "expected_state": expected_state,
            "status": payload["status"],
            "diffs": payload["steps"][0]["diffs"],
        }
        return "ran dynamic {} scenario".format(
            "recovery" if expected_match else "mutation"
        )

    def dynamic_export(self):
        case_id = self.window_case_ids()[0]
        self.dynamic_case(case_id)
        panel = self.window.dynamic_validation_panel
        target = self.artifact_dir / "dynamic-exports" / (
            self._case_name + ".json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        _schedule_file_dialog_path(target)
        _press(panel.export_button)
        self._wait_until(target.is_file, timeout_ms=10000)
        payload = json.loads(target.read_text(encoding="utf-8"))
        report = payload.get("report", payload)
        if report.get("case_id") != case_id:
            raise RuntimeError("dynamic report export lost the selected case")
        artifact = _artifact(target, self.artifact_dir)
        self.artifacts.append(artifact)
        self._current_evidence = {
            "case_id": case_id,
            "size": artifact["size"],
            "sha256": artifact["sha256"],
        }
        return "exported the visible dynamic-validation report through its button"

    def dynamic_terminology(self):
        journey = self._activate_workspace_shortcut(
            self.window.action_show_dynamic_validation,
            self.window.dynamic_validation_workspace,
            "dynamic_case_combo",
        )
        notice = self.window.dynamic_validation_panel.scope_notice
        if not notice.isVisibleTo(self.window):
            raise RuntimeError("dynamic-validation scope notice is not visible")
        text = notice.text()
        if "不是形式化验证" not in text or "expected/actual" not in text:
            raise RuntimeError("dynamic-validation terminology is incomplete")
        self._current_evidence = {
            "journey": journey,
            "notice_object": notice.objectName(),
            "visible": True,
            "text": text,
        }
        return "visible UI states that dynamic validation is not formal verification"

    def formula_case(self, kind, validity):
        valid = validity == "valid"
        root = self.window.state_manager.root_state
        if kind in ("guard", "effect"):
            dialog = DialogAddTransition(
                self.window,
                self.window.state_manager,
                root,
                mutate_model=False,
            )
            dialog.show()
            self.app.processEvents()
            self._keyboard_text(dialog.edit_source_state, "Idle")
            self._keyboard_text(dialog.edit_target_state, "Running")
            if kind == "guard":
                self._keyboard_text(dialog.edit_op, "count = count + 1;")
                other_token = dialog.effect_formula_editor.pending_request.request_token
                self._wait_until(
                    lambda: dialog.effect_formula_editor.last_result is not None
                    and dialog.effect_formula_editor.last_result.request_token
                    == other_token,
                    timeout_ms=3000,
                )
                field = dialog.edit_condition
                editor = dialog.condition_formula_editor
                text = "count >= 0" if valid else "count +"
            else:
                self._keyboard_text(dialog.edit_condition, "count >= 0")
                other_token = dialog.condition_formula_editor.pending_request.request_token
                self._wait_until(
                    lambda: dialog.condition_formula_editor.last_result is not None
                    and dialog.condition_formula_editor.last_result.request_token
                    == other_token,
                    timeout_ms=3000,
                )
                field = dialog.edit_op
                editor = dialog.effect_formula_editor
                text = "count = count + 1;" if valid else "count = ;"
            self._keyboard_text(field, text)
            token = editor.pending_request.request_token
            self._wait_until(
                lambda: editor.last_result is not None
                and editor.last_result.request_token == token,
                timeout_ms=3000,
            )
            if editor.is_valid is not valid:
                raise RuntimeError("{} validation result is incorrect".format(kind))
            if valid:
                _schedule_message_box_accept()
                _press(dialog.button_accept)
                if dialog.result() != QtWidgets.QDialog.Accepted:
                    raise RuntimeError(kind + " valid submit was rejected")
            else:
                _schedule_message_box_accept()
                _press(dialog.button_accept)
                if dialog.result() == QtWidgets.QDialog.Accepted:
                    raise RuntimeError(kind + " invalid submit was accepted")
        elif kind == "lifecycle":
            dialog = DialogAddLifecycle(
                self.window,
                self.window.state_manager,
                root,
                mutate_model=False,
            )
            dialog.show()
            self.app.processEvents()
            field = dialog.edit_op
            editor = dialog.lifecycle_formula_editor
            text = "count = count + 1;" if valid else "count = ;"
            self._keyboard_text(field, text)
            token = editor.pending_request.request_token
            self._wait_until(
                lambda: editor.last_result is not None
                and editor.last_result.request_token == token,
                timeout_ms=3000,
            )
            if editor.is_valid is not valid:
                raise RuntimeError("lifecycle validation result is incorrect")
            if valid:
                _schedule_message_box_accept()
                _press(dialog.button_accept)
                if dialog.result() != QtWidgets.QDialog.Accepted:
                    raise RuntimeError("lifecycle valid submit was rejected")
            else:
                _schedule_message_box_accept()
                _press(dialog.button_accept)
                if dialog.result() == QtWidgets.QDialog.Accepted:
                    raise RuntimeError("lifecycle invalid submit was accepted")
        elif kind == "numeric":
            dialog = DialogNumericFormula(
                self.window,
                revision_provider=lambda: self.window.document_session.source_revision,
                variable_definitions_provider=lambda: "def int count = 0;",
                debounce_ms=20,
            )
            dialog.show()
            self.app.processEvents()
            text = "count + 1" if valid else "count > 0"
            self._keyboard_text(dialog.input_field, text)
            token = dialog.formula_editor.pending_request.request_token
            self._wait_until(
                lambda: dialog.formula_editor.last_result is not None
                and dialog.formula_editor.last_result.request_token == token,
                timeout_ms=3000,
            )
            accept = dialog.button_box.button(QtWidgets.QDialogButtonBox.Ok)
            if dialog.formula_editor.is_valid is not valid:
                raise RuntimeError("numeric validation result is incorrect")
            if accept.isEnabled() is not valid:
                raise RuntimeError("numeric submit gate does not match validation")
            _press(accept)
            if valid and dialog.result() != QtWidgets.QDialog.Accepted:
                raise RuntimeError("numeric valid submit was rejected")
            if not valid and dialog.result() == QtWidgets.QDialog.Accepted:
                raise RuntimeError("numeric invalid submit was accepted")
        else:
            raise RuntimeError("unknown formula kind: " + kind)
        self._current_evidence = {
            "kind": kind,
            "validity": validity,
            "text": text,
            "accepted": valid,
        }
        dialog.close()
        return "validated {} {} formula through its dialog".format(validity, kind)

    def formula_stale(self):
        dialog = DialogNumericFormula(
            self.window,
            revision_provider=lambda: self.window.document_session.source_revision,
            variable_definitions_provider=lambda: "def int count = 0;",
            debounce_ms=1000,
        )
        dialog.show()
        self.app.processEvents()
        before_revision = self.window.document_session.source_revision
        self._keyboard_text(dialog.input_field, "count + 1")
        request = dialog.formula_editor.pending_request
        if request is None or request.source_revision != before_revision:
            raise RuntimeError("formula debounce request was not captured")
        editor = self.window.source_editor
        editor.moveCursor(QtGui.QTextCursor.End)
        _wait_signal(
            self.window.document_validation_finished,
            lambda: QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return),
            accept=self._is_current_validation,
        )
        after_revision = self.window.document_session.source_revision
        if after_revision <= before_revision:
            raise RuntimeError("source edit did not advance revision")
        QtTest.QTest.qWait(1200)
        result = dialog.formula_editor.last_result
        if result is not None and result.request_token == request.request_token:
            raise RuntimeError("stale formula result was published")
        self._current_evidence = {
            "request_token": request.request_token,
            "request_revision": before_revision,
            "current_revision": after_revision,
            "stale_result_published": False,
        }
        dialog.close()
        return "dropped formula result from an older source revision"

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

    def generation_template(self, template_name):
        dialog = DialogCodeGen(
            self.window, self.window.generation_service.list_templates()
        )
        dialog.generate_requested.connect(
            lambda request: self.window._start_generation(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("code-generation")
        )
        output = self.artifact_dir / "generated" / self._case_name
        dialog.show()
        self.app.processEvents()
        _select_combo_data(dialog.template_combo, template_name)
        self._keyboard_text(dialog.output_edit, str(output))
        result = _wait_signal(
            self.window.generation_finished,
            lambda: _press(dialog.generate_button),
        )[0]
        files = sorted(item for item in output.rglob("*") if item.is_file())
        if result.status.value != "success" or not files:
            raise RuntimeError(template_name + " generated no files")
        for path in files:
            self.artifacts.append(_artifact(path, self.artifact_dir))
        self._current_evidence = {
            "template": template_name,
            "file_count": len(files),
            "files": [path.relative_to(output).as_posix() for path in files],
        }
        dialog.close()
        return "generated {} with {} files".format(template_name, len(files))

    def _generation_dialog(self):
        dialog = DialogCodeGen(
            self.window, self.window.generation_service.list_templates()
        )
        dialog.generate_requested.connect(
            lambda request: self.window._start_generation(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("code-generation")
        )
        dialog.show()
        self.app.processEvents()
        return dialog

    def generation_custom(self):
        template = self.source_path.parent / "custom-template"
        template.mkdir()
        (template / "config.yaml").write_text("{}\n", encoding="utf-8")
        (template / "machine.txt.j2").write_text(
            "{{ model.root_state.name }}\n", encoding="utf-8"
        )
        output = self.artifact_dir / "generated" / self._case_name
        dialog = self._generation_dialog()
        dialog.template_mode_combo.setFocus(QtCore.Qt.TabFocusReason)
        QtTest.QTest.keyClick(dialog.template_mode_combo, QtCore.Qt.Key_Down)
        QtTest.QTest.keyClick(dialog.template_mode_combo, QtCore.Qt.Key_Tab)
        self._keyboard_text(dialog.custom_template_edit, str(template))
        self._keyboard_text(dialog.output_edit, str(output))
        result = _wait_signal(
            self.window.generation_finished,
            lambda: _press(dialog.generate_button),
        )[0]
        target = output / "machine.txt"
        if result.status.value != "success" or target.read_text(encoding="utf-8").strip() != "Root":
            raise RuntimeError("custom template did not render the model root")
        artifact = _artifact(target, self.artifact_dir)
        self.artifacts.append(artifact)
        self._current_evidence = {
            "template": "custom",
            "file": "machine.txt",
            "sha256": artifact["sha256"],
        }
        dialog.close()
        return "generated a real custom template"

    def generation_overwrite(self):
        output = self.artifact_dir / "generated" / self._case_name
        output.mkdir(parents=True)
        old = output / "old.txt"
        old.write_text("old", encoding="utf-8")
        dialog = self._generation_dialog()
        _select_combo_data(dialog.template_combo, "python")
        self._keyboard_text(dialog.output_edit, str(output))
        dialog.overwrite_check.setFocus(QtCore.Qt.TabFocusReason)
        QtTest.QTest.keyClick(dialog.overwrite_check, QtCore.Qt.Key_Space)
        _schedule_message_box_choice(QtWidgets.QMessageBox.Yes)
        result = _wait_signal(
            self.window.generation_finished,
            lambda: _press(dialog.generate_button),
        )[0]
        if result.status.value != "success" or old.exists():
            raise RuntimeError("generation overwrite did not atomically replace old output")
        if not (output / "machine.py").is_file():
            raise RuntimeError("generation overwrite published no Python runtime")
        self._current_evidence = {
            "old_removed": True,
            "replacement_files": dialog.result_table.rowCount(),
        }
        dialog.close()
        return "confirmed and replaced an existing generation directory"

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

    def export_kind(self, kind):
        if kind == "dynamic-json":
            self.dynamic_validation()
        dialog = DialogExport(
            self.window,
            dynamic_available=self.window.dynamic_validation_panel.report_json() is not None,
        )
        dialog.export_requested.connect(
            lambda request: self.window._start_unified_export(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("unified-export")
        )
        suffix = DialogExport.KIND_SUFFIXES[kind]
        target = self.artifact_dir / "exports" / (self._case_name + "." + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        dialog.show()
        self.app.processEvents()
        _select_combo_data(dialog.kind_combo, kind)
        self._keyboard_text(dialog.path_edit, str(target))
        result = _wait_signal(
            self.window.unified_export_finished,
            lambda: _press(dialog.start_button),
            timeout_ms=30000,
        )[0]
        if result.status.value != "success" or not target.is_file():
            raise RuntimeError(kind + " export failed")
        data = target.read_bytes()
        signatures = {
            "fcstm": b"state Root",
            "docx": b"PK",
            "xlsx": b"PK",
            "plantuml": b"@startuml",
            "png": b"\x89PNG\r\n\x1a\n",
            "svg": b"<svg",
            "pdf": b"%PDF",
        }
        if kind in signatures and signatures[kind] not in data[:4096]:
            raise RuntimeError(kind + " export has invalid magic/content")
        if kind.endswith("json"):
            payload = json.loads(data.decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(kind + " JSON root is not an object")
        artifact = _artifact(target, self.artifact_dir)
        self.artifacts.append(artifact)
        self._current_evidence = {
            "kind": kind,
            "size": artifact["size"],
            "sha256": artifact["sha256"],
        }
        dialog.close()
        return "exported and validated " + kind

    def task_results(self):
        self.simulation()
        dock = self.window.task_result_dock
        dock.show()
        dock.refresh()
        self.app.processEvents()
        if dock.table.rowCount() < 2:
            raise RuntimeError("explicit task history is incomplete")
        dock.table.setCurrentCell(0, 0)
        dock.table.selectRow(0)
        _press(dock.copy_button)
        copied = self.app.clipboard().text()
        if 'task_id' not in copied or str(self.artifact_dir) in copied:
            raise RuntimeError("task copy is empty or leaks the workspace path")
        self.artifacts.append(
            _screenshot(
                self.window,
                self.artifact_dir,
                "08-task-results-{}-{}x{}".format(
                    self._case_name, *self.viewport
                ),
            )
        )
        return "{} task rows, redacted keyboard copy".format(dock.table.rowCount())

    def task_filter(self):
        self.simulation()
        dock = self.window.task_result_dock
        dock.show()
        dock.refresh()
        self.app.processEvents()
        _select_combo_data(dock.status_filter, "success")
        _keyboard_replace(dock.search_edit, "普通仿真")
        self.app.processEvents()
        if dock.table.rowCount() < 1:
            raise RuntimeError("task status/search filter hid all matching records")
        visible = [
            dock.table.item(row, 3).text()
            for row in range(dock.table.rowCount())
        ]
        if not all("仿真" in summary for summary in visible):
            raise RuntimeError("task search returned an unrelated record")
        self._current_evidence = {
            "status": "success",
            "search": "普通仿真",
            "visible_rows": dock.table.rowCount(),
        }
        return "filtered successful ordinary-simulation tasks"

    def _task_dock_with_simulation(self):
        self.simulation()
        dock = self.window.task_result_dock
        dock.show()
        dock.refresh()
        self.app.processEvents()
        dock.table.selectRow(0)
        return dock

    def task_export_log(self):
        dock = self._task_dock_with_simulation()
        target = self.artifact_dir / "task-logs" / (self._case_name + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        _schedule_file_dialog_path(target)
        _press(dock.export_button)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if "task_id" not in payload or str(self.artifact_dir) in target.read_text(
            encoding="utf-8"
        ):
            raise RuntimeError("exported task log is empty or leaks a raw path")
        artifact = _artifact(target, self.artifact_dir)
        self.artifacts.append(artifact)
        self._current_evidence = {
            "task_id": payload["task_id"],
            "sha256": artifact["sha256"],
        }
        return "exported a redacted task log"

    def task_clear_filtered(self):
        self.document_failed_load_preserves_session()
        self.simulation()
        dock = self.window.task_result_dock
        dock.show()
        dock.refresh()
        self.app.processEvents()
        before = tuple(dock._visible_records)
        if not any(item.status.value == "success" for item in before):
            raise RuntimeError("clear-filtered fixture has no successful task")
        if not any(item.status.value == "failed" for item in before):
            raise RuntimeError("clear-filtered fixture has no failed task")
        _select_combo_data(dock.status_filter, "success")
        filtered = dock.table.rowCount()
        _schedule_message_box_choice(QtWidgets.QMessageBox.Yes)
        _press(dock.clear_filtered_button)
        _select_combo_data(dock.status_filter, None)
        remaining = tuple(dock._visible_records)
        if filtered < 1 or any(item.status.value == "success" for item in remaining):
            raise RuntimeError("clear filtered retained a matching successful task")
        if not any(item.status.value == "failed" for item in remaining):
            raise RuntimeError("clear filtered removed an unrelated failed task")
        self._current_evidence = {
            "filtered_removed": filtered,
            "remaining_statuses": sorted(
                {item.status.value for item in remaining}
            ),
        }
        return "cleared only the currently filtered persistent task records"

    def task_redaction(self):
        self.task_results()
        dock = self.window.task_result_dock
        if dock.show_full_paths_action.isChecked():
            raise RuntimeError("task paths defaulted to full-path mode")
        raw_path = str(self.source_path.parent.resolve())
        visible_payload = dock.detail.toPlainText() + self.app.clipboard().text()
        if raw_path in visible_payload:
            raise RuntimeError("default task detail/copy leaked a raw local path")
        self._current_evidence = {
            "default_full_paths": False,
            "raw_path_absent": True,
            "copy_tooltip": dock.copy_button.toolTip(),
            "export_tooltip": dock.export_button.toolTip(),
        }
        return "kept task detail and copy output redacted by default"

    def task_registry(self, operation):
        expected_kinds = {
            "load": "document-load",
            "inspect": "model-check",
            "graph": "graph-render",
            "simulation": "ordinary-simulation",
            "dynamic": "dynamic-validation",
            "generation": "code-generation",
            "export": "unified-export",
        }
        if operation == "load":
            self.recent_reopen()
        elif operation == "inspect":
            _wait_signal(
                self.window.model_check_finished,
                lambda: QtTest.QTest.keySequence(
                    self.window,
                    self.window.action_validate_state_machine.shortcut(),
                ),
            )
        elif operation == "graph":
            self.graph_smetana_semantics()
        elif operation == "simulation":
            self.simulation_initialize()
        elif operation == "dynamic":
            self.dynamic_case(self.window_case_ids()[0])
        elif operation == "generation":
            self.generation_template("python")
        elif operation == "export":
            self.export_kind("inspect-json")
        else:
            raise RuntimeError("unknown task registry operation: " + operation)
        expected_kind = expected_kinds[operation]
        matches = [
            record
            for record in self.window.task_center.records
            if record.kind == expected_kind
        ]
        if not matches or matches[-1].status.value != "success":
            raise RuntimeError(expected_kind + " did not register successful history")
        self._current_evidence = {
            "operation": operation,
            "kind": expected_kind,
            "status": matches[-1].status.value,
            "task_id": matches[-1].task_id,
            "history_count": len(self.window.task_center.records),
        }
        return "registered persistent {} task history".format(expected_kind)

    def task_transient(self, operation):
        before_ids = tuple(
            record.task_id for record in self.window.task_center.records
        )
        if operation == "document-validation":
            self.source_case("edit")
            forbidden_kind = "document-validate"
        elif operation == "formula-validation":
            self.formula_case("guard", "valid")
            forbidden_kind = "formula-validation"
        else:
            raise RuntimeError("unknown transient operation: " + operation)
        self.app.processEvents()
        after = tuple(self.window.task_center.records)
        if any(record.kind == forbidden_kind for record in after):
            raise RuntimeError(operation + " leaked into persistent task history")
        after_ids = tuple(record.task_id for record in after)
        if after_ids != before_ids:
            raise RuntimeError(operation + " changed persistent task history")
        self._current_evidence = {
            "operation": operation,
            "persistent_history_unchanged": True,
            "history_count": len(after),
            "forbidden_kind": forbidden_kind,
        }
        return "kept {} feedback transient".format(operation)

    def task_clear_completed(self):
        dock = self._task_dock_with_simulation()
        before = dock.table.rowCount()
        _schedule_message_box_choice(QtWidgets.QMessageBox.Yes)
        _press(dock.clear_completed_button)
        if before < 2 or dock.table.rowCount() != 0:
            raise RuntimeError("clear completed did not remove successful records")
        self._current_evidence = {"removed": before, "remaining": 0}
        return "cleared completed task records after confirmation"

    def task_clear_all(self):
        dock = self._task_dock_with_simulation()
        before = dock.table.rowCount()
        _schedule_message_box_choice(QtWidgets.QMessageBox.Yes)
        _press(dock.clear_all_button)
        if before < 2 or dock.table.rowCount() != 0:
            raise RuntimeError("clear all did not remove task history")
        self._current_evidence = {"removed": before, "remaining": 0}
        return "cleared all task history after confirmation"

    def task_retry(self):
        self.recent_reopen()
        dock = self.window.task_result_dock
        dock.show()
        dock.refresh()
        self.app.processEvents()
        row = next(
            index
            for index, record in enumerate(dock._visible_records)
            if record.kind == "document-load" and record.status.value == "success"
        )
        dock.table.selectRow(row)
        before_session = self.window.document_session.session_id
        _wait_signal(
            self.window.document_load_finished,
            lambda: _press(dock.retry_button),
        )
        if self.window.document_session.session_id == before_session:
            raise RuntimeError("task retry did not create a fresh document session")
        self._current_evidence = {
            "retried_kind": "document-load",
            "fresh_session": True,
        }
        return "retried a document-load task through the task dock"

    def task_artifact(self):
        self.export_kind("inspect-json")
        dock = self.window.task_result_dock
        dock.show()
        dock.refresh()
        self.app.processEvents()
        row = next(
            index
            for index, record in enumerate(dock._visible_records)
            if record.kind == "unified-export" and record.artifacts
        )
        dock.table.selectRow(row)
        self.app.processEvents()
        if dock.artifact_list.count() != 1:
            raise RuntimeError("task artifact list did not expose the export")
        if not dock.open_artifact_button.isEnabled():
            raise RuntimeError("existing task artifact cannot be opened")
        artifact = dock.selected_artifact
        self._current_evidence = {
            "artifact_label": artifact.label,
            "artifact_kind": artifact.kind,
            "raw_path_available": artifact.raw_path_available,
        }
        return "exposed a real task artifact entry and action"

    def cancel_load(self):
        target = self.source_path.parent / "large.fcstm"
        target.write_text("// load padding\n" * 20000 + _SOURCE, encoding="utf-8")

        def start_and_cancel():
            _schedule_file_dialog_path(target)
            QtTest.QTest.keySequence(
                self.window, self.window.action_import_state_machine.shortcut()
            )
            dock = self.window.task_result_dock
            dock.show()
            dock.refresh()
            self.app.processEvents()
            row = next(
                index
                for index, record in enumerate(dock._visible_records)
                if record.kind == "document-load" and record.status.value == "running"
            )
            dock.table.selectRow(row)
            _press(dock.cancel_button)

        outcome = _wait_signal(
            self.window.document_load_finished,
            start_and_cancel,
            timeout_ms=30000,
        )[0]
        if outcome.status.value != "cancelled":
            raise RuntimeError("load cancellation finished as " + outcome.status.value)
        self._current_evidence = {
            "status": outcome.status.value,
            "session_preserved": self.window.document_session.path
            == str(self.source_path.resolve()),
        }
        return "cancelled a running document load through the stop shortcut"

    def cancel_dynamic(self):
        panel = self.window.dynamic_validation_panel
        self._activate_workspace_shortcut(
            self.window.action_show_dynamic_validation,
            self.window.dynamic_validation_workspace,
            "dynamic_case_combo",
        )

        def start_and_cancel():
            _press(panel.run_suite_button)
            if not panel.cancel_button.isEnabled():
                raise RuntimeError("dynamic task did not expose cancel")
            _press(panel.cancel_button)

        result = _wait_signal(
            self.window.dynamic_validation_finished, start_and_cancel
        )[0]
        if result.status.value != "cancelled" and panel.report.status != "cancelled":
            raise RuntimeError("dynamic cancellation did not reach a cancelled state")
        self._current_evidence = {"status": "cancelled"}
        return "cancelled dynamic validation through its stop button"

    def cancel_graph(self):
        panel = self.window.graph_panel
        self._activate_workspace_shortcut(
            self.window.action_show_graph,
            self.window.graph_workspace,
            "graph_refresh_button",
        )

        def start_and_cancel():
            _press(panel.refresh_button)
            if not panel.cancel_button.isEnabled():
                raise RuntimeError("graph task did not expose cancel")
            _press(panel.cancel_button)

        result = _wait_signal(self.window.graph_task_finished, start_and_cancel)[0]
        if result.status.value != "cancelled":
            raise RuntimeError("graph cancellation finished as " + result.status.value)
        self._current_evidence = {"status": result.status.value}
        return "cancelled graph rendering through its stop button"

    def _large_custom_template(self, name, file_count=300):
        template = self.source_path.parent / name
        template.mkdir()
        (template / "config.yaml").write_text("{}\n", encoding="utf-8")
        for index in range(file_count):
            (template / ("file-{:03d}.txt.j2".format(index))).write_text(
                "{{ model.root_state.name }}\n", encoding="utf-8"
            )
        return template

    def cancel_generation(self):
        template = self._large_custom_template("cancel-template")
        output = self.artifact_dir / "generated" / self._case_name
        dialog = self._generation_dialog()
        dialog.template_mode_combo.setFocus(QtCore.Qt.TabFocusReason)
        QtTest.QTest.keyClick(dialog.template_mode_combo, QtCore.Qt.Key_Down)
        self._keyboard_text(dialog.custom_template_edit, str(template))
        self._keyboard_text(dialog.output_edit, str(output))

        def start_and_cancel():
            _press(dialog.generate_button)
            if not dialog.cancel_button.isEnabled():
                raise RuntimeError("generation did not expose cancel")
            _press(dialog.cancel_button)

        result = _wait_signal(self.window.generation_finished, start_and_cancel)[0]
        if result.status.value != "cancelled" or output.exists():
            raise RuntimeError("generation cancellation published output")
        self._current_evidence = {
            "status": result.status.value,
            "target_absent": True,
        }
        dialog.close()
        return "cancelled generation without publishing its target"

    def cancel_export(self):
        dialog = DialogExport(self.window)
        dialog.export_requested.connect(
            lambda request: self.window._start_unified_export(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("unified-export")
        )
        target = self.artifact_dir / "exports" / (self._case_name + ".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        dialog.show()
        _select_combo_data(dialog.kind_combo, "png")
        self._keyboard_text(dialog.path_edit, str(target))

        def start_and_cancel():
            _press(dialog.start_button)
            if not dialog.cancel_button.isEnabled():
                raise RuntimeError("export did not expose cancel")
            _press(dialog.cancel_button)

        result = _wait_signal(
            self.window.unified_export_finished, start_and_cancel
        )[0]
        if result.status.value != "cancelled" or target.exists():
            raise RuntimeError("export cancellation published a target")
        self._current_evidence = {
            "status": result.status.value,
            "target_absent": True,
        }
        dialog.close()
        return "cancelled export without publishing its target"

    def _make_source_stale(self):
        editor = self.window.source_editor
        editor.moveCursor(QtGui.QTextCursor.End)
        QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return)
        self.app.processEvents()

    def stale_task(self, kind):
        dialog = None
        if kind == "graph":
            signal = self.window.graph_task_finished
            trigger_button = self.window.graph_panel.refresh_button
            self._activate_workspace_shortcut(
                self.window.action_show_graph,
                self.window.graph_workspace,
                "graph_refresh_button",
            )

            def start():
                _press(trigger_button)
                self._make_source_stale()
        elif kind == "simulation":
            panel, _session = self._initialize_simulation_case()
            self._keyboard_text(panel.event_edit, "")
            self._keyboard_text(panel.cycle_count, "10000")
            QtTest.QTest.keyClick(panel.cycle_count, QtCore.Qt.Key_Enter)
            signal = self.window.simulation_task_finished

            def start():
                _press(panel.run_button)
                self._make_source_stale()
        elif kind == "dynamic":
            panel = self.window.dynamic_validation_panel
            signal = self.window.dynamic_validation_finished

            def start():
                _press(panel.run_suite_button)
                self._make_source_stale()
        elif kind == "generation":
            template = self._large_custom_template("stale-template")
            output = self.artifact_dir / "generated" / self._case_name
            dialog = self._generation_dialog()
            dialog.template_mode_combo.setFocus(QtCore.Qt.TabFocusReason)
            QtTest.QTest.keyClick(dialog.template_mode_combo, QtCore.Qt.Key_Down)
            self._keyboard_text(dialog.custom_template_edit, str(template))
            self._keyboard_text(dialog.output_edit, str(output))
            signal = self.window.generation_finished

            def start():
                _press(dialog.generate_button)
                self._make_source_stale()
        elif kind == "export":
            target = self.artifact_dir / "exports" / (self._case_name + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            dialog = DialogExport(self.window)
            dialog.export_requested.connect(
                lambda request: self.window._start_unified_export(request, dialog)
            )
            dialog.show()
            _select_combo_data(dialog.kind_combo, "png")
            self._keyboard_text(dialog.path_edit, str(target))
            signal = self.window.unified_export_finished

            def start():
                _press(dialog.start_button)
                self._make_source_stale()
        else:
            raise RuntimeError("unknown stale task: " + kind)
        result = _wait_signal(signal, start, timeout_ms=30000)[0]
        if result.status.value != "stale":
            raise RuntimeError("{} stale task finished as {}".format(kind, result.status.value))
        self._current_evidence = {
            "kind": kind,
            "status": result.status.value,
            "revision": self.window.document_session.source_revision,
        }
        if dialog is not None:
            dialog.close()
        return "rejected stale {} publication".format(kind)

    def keyboard_case(self, kind):
        before_widget = self.app.focusWidget()
        before_focus = "" if before_widget is None else before_widget.objectName()
        if kind == "inspect":
            self.diagnostics_conflict()
            self.window.activateWindow()
            self.window.setFocus(QtCore.Qt.ActiveWindowFocusReason)
            _wait_signal(
                self.window.model_check_finished,
                lambda: QtTest.QTest.keySequence(
                    self.window, self.window.action_validate_state_machine.shortcut()
                ),
            )
            journey = self._activate_workspace_shortcut(
                self.window.action_show_diagnostics,
                self.window.diagnostics_workspace,
                "diagnostics_table",
            )
            detail = "ran inspect and reached structured diagnostics"
            sequence = "F5 -> {}".format(journey["shortcut"])
        elif kind == "generation":
            detail = self.generation_template("python")
            sequence = "generation dialog -> Home -> output -> Space"
        elif kind == "templates":
            dialog = self._generation_dialog()
            combo = dialog.template_combo
            combo.setFocus(QtCore.Qt.TabFocusReason)
            QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Home)
            visited = [combo.currentData()]
            for _unused in range(4):
                QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Down)
                visited.append(combo.currentData())
            expected = {"python", "c", "c_poll", "cpp", "cpp_poll"}
            if set(visited) != expected or len(visited) != len(expected):
                raise RuntimeError("keyboard template order is incomplete: {}".format(visited))
            self._current_evidence = {"templates": visited}
            dialog.close()
            detail = "reached all five built-in templates by arrow keys"
            sequence = "Home -> Down x4"
        elif kind == "graph":
            detail = self.graph_interaction("reset")
            sequence = "workspace shortcut -> refresh Space -> reset Space"
        elif kind == "simulation":
            detail = self.simulation_pause_continue(continue_run=True)
            sequence = "workspace shortcut -> init/cycle/run/pause/continue Space"
        elif kind == "syntax":
            detail = self.source_save_fresh_reload()
            sequence = "source shortcut -> edit -> Save -> Open -> Enter"
        elif kind.startswith("formula."):
            formula_kind = kind.split(".", 1)[1]
            self.formula_case(formula_kind, "valid")
            detail = self.formula_case(formula_kind, "invalid")
            sequence = "dialog field -> SelectAll -> type -> submit"
        else:
            raise RuntimeError("unknown keyboard case: " + kind)
        after_widget = self.app.focusWidget()
        after_focus = "" if after_widget is None else after_widget.objectName()
        self._current_evidence.update(
            {
                "key_sequence": sequence,
                "focus_before": before_focus,
                "focus_after": after_focus,
                "business_fact": detail,
            }
        )
        return "completed keyboard {} journey".format(kind)

    def keyboard_model(self):
        journey = self._activate_workspace_shortcut(
            self.window.action_show_model,
            self.window.model_workspace,
            "tree_all_state",
        )
        tree = self.window.tree_all_state
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key_Home)
        root = tree.currentItem()
        if root is None or root.text(0) != "Root":
            raise RuntimeError("keyboard tree navigation did not select Root")
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key_Left)
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key_Right)
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key_Down)
        item = tree.currentItem()
        if item is None or item.text(0) != "Idle":
            raise RuntimeError("keyboard tree navigation did not select Idle")
        before_revision = self.window.document_session.source_revision
        _schedule_state_rename_dialog("Ready")
        rect = tree.visualItemRect(item)
        viewport = tree.viewport()
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Keyboard,
            rect.center(),
            viewport.mapToGlobal(rect.center()),
        )
        QtWidgets.QApplication.postEvent(viewport, event)
        self.app.processEvents()
        self._wait_until(
            lambda: self.window.document_session.source_revision > before_revision,
            timeout_ms=5000,
        )
        if "state Ready;" not in self.window.document_session.source_text:
            raise RuntimeError("keyboard model edit did not change the selected state")
        self._current_evidence = {
            "journey": journey,
            "key_sequence": (
                "model shortcut -> Home -> Left -> Right -> Down -> Menu -> Down -> Enter"
            ),
            "focus_before": journey["focus_before"],
            "focus_after": tree.objectName(),
            "selected_before": "Idle",
            "selected_after": "Ready",
            "revision_before": before_revision,
            "revision_after": self.window.document_session.source_revision,
        }
        return "renamed the selected model state through a keyboard context menu"

    def graph_drag(self):
        self.graph_smetana_semantics()
        panel = self.window.graph_panel
        _press(panel.actual_button)
        view = panel.view
        viewport = view.viewport()
        start = viewport.rect().center()
        wheel_steps = 0
        while (
            view.horizontalScrollBar().maximum() <= 0
            and view.verticalScrollBar().maximum() <= 0
            and wheel_steps < 12
        ):
            wheel = QtGui.QWheelEvent(
                QtCore.QPointF(start),
                QtCore.QPointF(viewport.mapToGlobal(start)),
                QtCore.QPoint(),
                QtCore.QPoint(0, 120),
                QtCore.Qt.NoButton,
                QtCore.Qt.NoModifier,
                QtCore.Qt.NoScrollPhase,
                False,
            )
            QtWidgets.QApplication.sendEvent(viewport, wheel)
            self.app.processEvents()
            wheel_steps += 1
        horizontal = view.horizontalScrollBar()
        vertical = view.verticalScrollBar()
        if horizontal.maximum() > 0:
            scrollbar = horizontal
            delta = QtCore.QPoint(-30, 0)
            orientation = "horizontal"
        elif vertical.maximum() > 0:
            scrollbar = vertical
            delta = QtCore.QPoint(0, -30)
            orientation = "vertical"
        else:
            raise RuntimeError("wheel zoom did not create a pannable graph range")
        before = scrollbar.value()
        end = start + delta
        QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, pos=start)
        move = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            end,
            viewport.mapToGlobal(end),
            QtCore.Qt.NoButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(viewport, move)
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=end)
        self.app.processEvents()
        after = scrollbar.value()
        if scrollbar.maximum() <= 0 or after == before:
            raise RuntimeError(
                "graph drag did not move the scroll position: {} -> {}".format(
                    before, after
                )
            )
        self._current_evidence = {
            "wheel_steps": wheel_steps,
            "orientation": orientation,
            "scroll_before": before,
            "scroll_after": after,
            "scroll_maximum": scrollbar.maximum(),
        }
        return "dragged the graph canvas through mouse events"

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

    def geometry_active_workspaces(self):
        self.window.resize(*self.viewport)
        self.app.processEvents()
        font_family = self.app.font().family()
        if font_family != EXPECTED_FAMILY:
            raise RuntimeError("bundled CJK font is not active: " + font_family)
        if self.app.font().pointSize() != APPLICATION_FONT_POINT_SIZE:
            raise RuntimeError("bundled application font size is not active")
        active_workspaces = []
        overlap_exemptions = []
        focus_chain_exemptions = [
            {
                "workspace": "source_workspace",
                "reason": "the source editor intentionally consumes Tab for text input",
            }
        ]
        focus_chain_exemption_pages = {
            item["workspace"] for item in focus_chain_exemptions
        }
        passed_results = {
            item["name"]: item
            for item in self.results
            if item.get("status") == "passed"
        }
        product_layout = os.environ.get("FCSTM_GUI_PRODUCT_LAYOUT", "source")
        qt_platform = QtWidgets.QApplication.platformName()
        platform_system = platform.system()
        style = self.app.style().objectName() or type(self.app.style()).__name__
        window_rect = self.window.rect()
        specs = self._workspace_specs()
        for index, (action, page, focus_name) in enumerate(specs, 1):
            journey = self._activate_workspace_shortcut(action, page, focus_name)
            point = page.mapTo(self.window, QtCore.QPoint(0, 0))
            rect = QtCore.QRect(point, page.size())
            visible = page.isVisibleTo(self.window)
            contained = window_rect.contains(rect)
            hidden_pages_visible = [
                other.objectName()
                for _other_action, other, _other_focus in specs
                if other is not page and other.isVisibleTo(self.window)
            ]
            if not visible or not contained or hidden_pages_visible:
                raise RuntimeError(
                    "workspace geometry invalid for {}: visible={}, contained={}, hidden={}".format(
                        page.objectName(), visible, contained, hidden_pages_visible
                    )
                )
            target = self.window.findChild(QtWidgets.QWidget, focus_name)
            target_point = target.mapTo(self.window, QtCore.QPoint(0, 0))
            target_rect = QtCore.QRect(target_point, target.size())
            if not target.isVisibleTo(self.window) or not window_rect.contains(target_rect):
                raise RuntimeError(focus_name + " is hidden or clipped")

            tab_bar = self.window.workspace_tabs.tabBar()
            tab_index = self.window.workspace_tabs.currentIndex()
            tab_rect = tab_bar.tabRect(tab_index)
            if (
                not tab_rect.isValid()
                or tab_rect.isEmpty()
                or not tab_bar.rect().contains(tab_rect)
            ):
                raise RuntimeError("current workspace tab is clipped or empty")

            focus_chain = [target.objectName() or type(target).__name__]
            seen = {id(target)}
            for _unused in range(3):
                if not self.window.focusNextPrevChild(True):
                    break
                cursor = self.app.focusWidget()
                if cursor is None or id(cursor) in seen:
                    break
                seen.add(id(cursor))
                cursor_point = cursor.mapTo(self.window, QtCore.QPoint(0, 0))
                cursor_rect = QtCore.QRect(cursor_point, cursor.size())
                if not window_rect.contains(cursor_rect):
                    raise RuntimeError(
                        "focus-chain widget is clipped: "
                        + (cursor.objectName() or type(cursor).__name__)
                    )
                focus_chain.append(cursor.objectName() or type(cursor).__name__)
            if (
                len(focus_chain) < 2
                and page.objectName() not in focus_chain_exemption_pages
            ):
                raise RuntimeError(
                    "workspace has no usable focus chain: " + page.objectName()
                )

            scroll_areas = []
            for area in page.findChildren(QtWidgets.QAbstractScrollArea):
                if (
                    isinstance(area, QtWidgets.QHeaderView)
                    or not area.isVisibleTo(self.window)
                ):
                    continue
                viewport_widget = area.viewport()
                viewport_point = viewport_widget.mapTo(
                    self.window, QtCore.QPoint(0, 0)
                )
                viewport_rect = QtCore.QRect(
                    viewport_point, viewport_widget.size()
                )
                ancestor = area.parentWidget()
                clipped_by_scroll_ancestor = False
                while ancestor is not None and ancestor is not page:
                    parent = ancestor.parentWidget()
                    if (
                        isinstance(parent, QtWidgets.QAbstractScrollArea)
                        and ancestor is parent.viewport()
                    ):
                        clip_point = ancestor.mapTo(
                            self.window, QtCore.QPoint(0, 0)
                        )
                        clip_rect = QtCore.QRect(clip_point, ancestor.size())
                        if not clip_rect.contains(viewport_rect):
                            clipped_by_scroll_ancestor = True
                            break
                    ancestor = parent
                if clipped_by_scroll_ancestor:
                    continue
                if viewport_rect.isEmpty() or not window_rect.contains(viewport_rect):
                    raise RuntimeError(
                        "scroll viewport is clipped: "
                        + (area.objectName() or type(area).__name__)
                    )
                ranges = {}
                for orientation, scrollbar in (
                    ("horizontal", area.horizontalScrollBar()),
                    ("vertical", area.verticalScrollBar()),
                ):
                    if not scrollbar.minimum() <= scrollbar.value() <= scrollbar.maximum():
                        raise RuntimeError("scrollbar value is outside its range")
                    ranges[orientation] = {
                        "minimum": scrollbar.minimum(),
                        "maximum": scrollbar.maximum(),
                        "value": scrollbar.value(),
                        "visible": scrollbar.isVisibleTo(self.window),
                    }
                scroll_areas.append(
                    {
                        "object_name": area.objectName() or type(area).__name__,
                        "viewport_rect": [
                            viewport_rect.x(), viewport_rect.y(),
                            viewport_rect.width(), viewport_rect.height(),
                        ],
                        "ranges": ranges,
                    }
                )

            headers = []
            for header in page.findChildren(QtWidgets.QHeaderView):
                if not header.isVisibleTo(self.window):
                    continue
                if header.rect().isEmpty() or header.viewport().rect().isEmpty():
                    continue
                headers.append(
                    {
                        "object_name": header.objectName() or type(header).__name__,
                        "section_count": header.count(),
                        "length": header.length(),
                    }
                )

            current_items = []
            for view in page.findChildren(QtWidgets.QAbstractItemView):
                if (
                    isinstance(view, QtWidgets.QHeaderView)
                    or not view.isVisibleTo(self.window)
                    or not view.currentIndex().isValid()
                ):
                    continue
                current_rect = view.visualRect(view.currentIndex())
                if current_rect.isEmpty() or not view.viewport().rect().contains(current_rect):
                    raise RuntimeError(
                        "current item is clipped: "
                        + (view.objectName() or type(view).__name__)
                    )
                current_items.append(
                    {
                        "object_name": view.objectName() or type(view).__name__,
                        "row": view.currentIndex().row(),
                        "column": view.currentIndex().column(),
                        "rect": [
                            current_rect.x(), current_rect.y(),
                            current_rect.width(), current_rect.height(),
                        ],
                    }
                )

            screenshot_artifact = _screenshot(
                self.window,
                self.artifact_dir,
                "geometry-{}-{}-{}x{}".format(
                    index, page.objectName(), *self.viewport
                ),
            )
            self.artifacts.append(screenshot_artifact)

            overlaps = []
            parents = [page] + page.findChildren(QtWidgets.QWidget)
            for parent in parents:
                controls = [
                    child
                    for child in parent.findChildren(
                        QtWidgets.QWidget, options=QtCore.Qt.FindDirectChildrenOnly
                    )
                    if child.isVisibleTo(self.window)
                    and child.focusPolicy() != QtCore.Qt.NoFocus
                    and not isinstance(child, QtWidgets.QScrollBar)
                ]
                for left_index, left in enumerate(controls):
                    for right in controls[left_index + 1:]:
                        intersection = left.geometry().intersected(right.geometry())
                        if intersection.width() <= 1 or intersection.height() <= 1:
                            continue
                        names = tuple(
                            sorted(
                                (
                                    left.objectName() or type(left).__name__,
                                    right.objectName() or type(right).__name__,
                                )
                            )
                        )
                        parent_name = parent.objectName() or type(parent).__name__
                        if _is_preapproved_native_overlap(
                            platform_system,
                            qt_platform,
                            parent_name,
                            names,
                        ):
                            acceptance_items = tuple(
                                _CONTROL_ACCEPTANCE[name]
                                for name in names
                            )
                            result_items = tuple(
                                passed_results.get(name) for name in acceptance_items
                            )
                            text_visible = all(
                                button.text()
                                and button.fontMetrics().horizontalAdvance(button.text())
                                <= max(0, button.width() - 12)
                                for button in (left, right)
                            )
                            hit_test_passed = all(
                                parent.childAt(button.geometry().center()) is button
                                for button in (left, right)
                            )
                            focus_passed = all(
                                button.focusPolicy() != QtCore.Qt.NoFocus
                                for button in (left, right)
                            )
                            accessible_name_passed = all(
                                button.accessibleName() and button.toolTip()
                                for button in (left, right)
                            )
                            business_fact_passed = all(result_items)
                            artifact_fact_passed = all(
                                item and item.get("artifacts") for item in result_items
                            )
                            functional_verdicts = (
                                text_visible,
                                hit_test_passed,
                                focus_passed,
                                accessible_name_passed,
                                business_fact_passed,
                                artifact_fact_passed,
                            )
                            if all(functional_verdicts):
                                viewport = "{}x{}".format(*self.viewport)
                                scale = os.environ.get("QT_SCALE_FACTOR", "1")
                                join_key = "|".join(
                                    (
                                        platform_system,
                                        product_layout,
                                        viewport,
                                        scale,
                                        "geometry.active-workspaces",
                                        names[0],
                                        names[1],
                                    )
                                )
                                overlap_exemptions.append(
                                    {
                                        "join_key": join_key,
                                        "platform": platform_system,
                                        "qt_platform": qt_platform,
                                        "style": style,
                                        "layout": product_layout,
                                        "viewport": viewport,
                                        "scale": scale,
                                        "acceptance_item": "geometry.active-workspaces",
                                        "parent": parent_name,
                                        "widgets": list(names),
                                        "intersection": [
                                            intersection.x(),
                                            intersection.y(),
                                            intersection.width(),
                                            intersection.height(),
                                        ],
                                        "reason": (
                                            "reviewed Cocoa native button geometry contact; "
                                            "all functional verdicts passed"
                                        ),
                                        "screenshot_path": screenshot_artifact["path"],
                                        "screenshot_sha256": screenshot_artifact["sha256"],
                                        "text_visible": True,
                                        "hit_test_passed": True,
                                        "click_passed": True,
                                        "focus_passed": True,
                                        "accessible_name_passed": True,
                                        "business_fact_passed": True,
                                        "artifact_fact_passed": True,
                                    }
                                )
                                continue
                        overlaps.append(
                            {
                                "parent": parent_name,
                                "widgets": list(names),
                                "intersection": [
                                    intersection.x(), intersection.y(),
                                    intersection.width(), intersection.height(),
                                ],
                            }
                        )
            if overlaps:
                raise RuntimeError(
                    "overlapping focusable controls: " + json.dumps(overlaps)
                )
            record = dict(journey)
            record.update(
                {
                    "visible_to_window": visible,
                    "contained_by_window": contained,
                    "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                    "focus_rect": [
                        target_rect.x(), target_rect.y(),
                        target_rect.width(), target_rect.height(),
                    ],
                    "hidden_pages_visible": hidden_pages_visible,
                    "current_tab_rect": [
                        tab_rect.x(), tab_rect.y(),
                        tab_rect.width(), tab_rect.height(),
                    ],
                    "focus_chain": focus_chain,
                    "scroll_areas": scroll_areas,
                    "headers": headers,
                    "current_items": current_items,
                    "overlaps": overlaps,
                }
            )
            active_workspaces.append(record)
        buttons = []
        for button in self.window.findChildren(QtWidgets.QAbstractButton):
            if not button.isVisibleTo(self.window):
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
            'font_family': font_family,
            'font_point_size': self.app.font().pointSize(),
            'active_workspaces': active_workspaces,
            'buttons': buttons,
            'overlap_exemptions': overlap_exemptions,
            'focus_chain_exemptions': focus_chain_exemptions,
        }
        self._current_evidence = {
            "workspace_count": len(active_workspaces),
            "all_visible_and_contained": True,
            "overlap_count": 0,
            "overlap_exemption_count": len(overlap_exemptions),
            "scroll_area_count": sum(
                len(item["scroll_areas"]) for item in active_workspaces
            ),
            "header_count": sum(
                len(item["headers"]) for item in active_workspaces
            ),
        }
        return '{} active workspaces and {} visible buttons checked'.format(
            len(active_workspaces), len(buttons)
        )

    def close(self):
        self._close_window()


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
            'qt_platform': QtGui.QGuiApplication.platformName(),
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
