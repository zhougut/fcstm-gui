#!/usr/bin/env python3
"""Replay source-mode GUI workflows and capture documentation screenshots."""

from __future__ import unicode_literals

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PyQt5 import QtCore, QtTest, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.acceptance_check import (  # noqa: E402
    AcceptanceDriver,
    _SOURCE,
    _keyboard_replace,
    _press,
    _schedule_file_dialog_path,
    _wait_signal,
)
from app.model.session import ValidationState  # noqa: E402
from app.widget import DialogCodeGen, DialogExport  # noqa: E402
from app.widget.dialog_add_lifecycle import DialogAddLifecycle  # noqa: E402
from app.widget.dialog_add_transition import DialogAddTransition  # noqa: E402
from app.widget.dialog_edit_state import DialogEditState  # noqa: E402
from app.widget.dialog_numeric_formula import DialogNumericFormula  # noqa: E402


DEFAULT_OUTPUT = ROOT / "docs" / "images" / "workflows"
WORKFLOWS = (
    "01-open-document",
    "02-diagnostics-navigation",
    "03-real-state-graph",
    "04-ordinary-simulation",
    "05-dynamic-validation",
    "06-five-template-generation",
    "07-unified-export",
    "08-task-results",
    "09-model-crud",
    "10-formulas",
    "11-cross-cutting",
)

# A source-reference image can illustrate a broader workflow than one stable
# acceptance item. Keep that relationship explicit instead of allowing old
# shorthand IDs to look like independent acceptance contracts.
SOURCE_REFERENCE_ALIASES = {
    "diagnostics.recover": "diagnostics.suggested-fix",
    "dynamic.suite": "dynamic.user",
    "export.existing-target": "export.overwrite-preserves-target",
    "generation.templates": "generation.python",
    "simulation.cycle": "simulation.step",
    "tasks.failure-filter": "tasks.filter",
    "tasks.history": "tasks.registry.load",
}


class WorkflowCapture(object):
    def __init__(self, output, viewport, scale):
        self.output = Path(output).resolve()
        self.viewport = tuple(viewport)
        self.scale = str(scale)
        self.images = []
        self.runtime = Path(tempfile.mkdtemp(prefix="fcstm-doc-capture-"))
        self.driver = AcceptanceDriver(self.runtime, self.viewport)
        self.driver._reset_case("workflow-documentation", with_document=False)
        self.window = self.driver.window
        self.app = self.driver.app

    def prepare(self):
        if self.output.exists():
            shutil.rmtree(str(self.output))
        for workflow in WORKFLOWS:
            (self.output / workflow).mkdir(parents=True, exist_ok=True)

    def capture(self, widget, workflow, filename, item, note):
        self.app.processEvents()
        target = self.output / workflow / filename
        image = widget.grab()
        if image.isNull() or not image.save(str(target), "PNG"):
            raise RuntimeError("failed to capture {}".format(target))
        data = target.read_bytes()
        if len(data) < 1000 or len(set(data[100:])) < 8:
            raise RuntimeError("blank or incomplete screenshot: {}".format(target))
        self.images.append(
            {
                "path": target.relative_to(self.output).as_posix(),
                "workflow": workflow,
                "stage": filename.split("-", 1)[0],
                "platform": platform.system().lower(),
                "viewport": "{}x{}".format(*self.viewport),
                "scale": self.scale,
                "font_family": self.app.font().family(),
                "font_point_size": self.app.font().pointSize(),
                "acceptance_id": item,
                "note": note,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "width": image.width(),
                "height": image.height(),
            }
        )

    def wait_with_running_capture(self, signal, trigger, capture):
        loop = QtCore.QEventLoop()
        payload = []
        timer = QtCore.QTimer()
        timer.setSingleShot(True)

        def finished(*args):
            payload.append(args)
            loop.quit()

        signal.connect(finished)
        timer.timeout.connect(loop.quit)
        try:
            trigger()
            self.app.processEvents()
            capture()
            if not payload:
                timer.start(20000)
                loop.exec_()
        finally:
            timer.stop()
            signal.disconnect(finished)
        if not payload:
            raise TimeoutError("GUI workflow did not finish")
        return payload[0]

    def wait_until(self, predicate, timeout_ms=3000):
        deadline = datetime.now().timestamp() + timeout_ms / 1000.0
        while datetime.now().timestamp() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QtTest.QTest.qWait(20)
        raise TimeoutError("GUI condition did not become true")

    def confirm_message_box(self, standard_button):
        def interact():
            modal = self.app.activeModalWidget()
            if isinstance(modal, QtWidgets.QMessageBox):
                button = modal.button(standard_button)
                if button is None:
                    raise RuntimeError("message box button is unavailable")
                _press(button)
                return
            QtCore.QTimer.singleShot(20, interact)

        QtCore.QTimer.singleShot(20, interact)

    def choose_file_dialog(self, path):
        _schedule_file_dialog_path(Path(path).resolve())

    def wait_formula(self, editor, expected_valid, timeout_ms=3000):
        self.wait_until(
            lambda: editor.last_result is not None
            and bool(editor.is_valid) is bool(expected_valid),
            timeout_ms=timeout_ms,
        )

    def open_document(self):
        workflow = WORKFLOWS[0]
        self.capture(
            self.window,
            workflow,
            "00-before.png",
            "document.open",
            "尚未打开文档的真实空工作台",
        )
        self.driver.document_open()
        self.capture(
            self.window,
            workflow,
            "03-result.png",
            "document.open",
            "Ctrl+O 加载完成后的模型投影和文档状态",
        )

    def diagnostics(self):
        workflow = WORKFLOWS[1]
        editor = self.window.source_editor
        self.window.action_show_source.trigger()
        self.capture(
            self.window,
            workflow,
            "00-before.png",
            "diagnostics.syntax",
            "有效源码进入诊断操作前",
        )
        _wait_signal(
            self.window.document_validation_finished,
            lambda: _keyboard_replace(editor, "state Broken { state ; }"),
            accept=self.driver._is_current_validation,
        )
        if self.window.document_session.validation_state is not ValidationState.INVALID_SYNTAX:
            raise RuntimeError("syntax fixture did not become invalid")
        self.window.action_show_diagnostics.trigger()
        self.capture(
            self.window,
            workflow,
            "01-action.png",
            "diagnostics.syntax",
            "结构化语法诊断、来源和定位动作",
        )
        panel = self.window.diagnostics_panel
        locate = panel.table.cellWidget(0, panel.COLUMN_ACTION)
        _press(locate)
        self.capture(
            self.window,
            workflow,
            "03-result.png",
            "diagnostics.locate",
            "定位后源码范围获得焦点和选择",
        )
        _wait_signal(
            self.window.document_validation_finished,
            lambda: _keyboard_replace(editor, _SOURCE),
            accept=self.driver._is_current_validation,
        )
        self.window.action_show_diagnostics.trigger()
        self.capture(
            self.window,
            workflow,
            "04-failure-recovery.png",
            "diagnostics.recover",
            "恢复有效源码后诊断清除且消费者重新可用",
        )

    def model_crud(self):
        workflow = WORKFLOWS[8]
        self.window.action_show_model.trigger()
        root_item = self.window.tree_all_state.topLevelItem(0)
        if root_item is None:
            raise RuntimeError("model tree has no root item")
        self.window.tree_all_state.setCurrentItem(root_item)
        QtTest.QTest.mouseClick(
            self.window.tree_all_state.viewport(),
            QtCore.Qt.LeftButton,
            pos=self.window.tree_all_state.visualItemRect(root_item).center(),
        )
        self.app.processEvents()
        self.capture(
            self.window,
            workflow,
            "00-before.png",
            "model.state.add",
            "从真实模型树选择 Root 后进入状态 CRUD",
        )

        dialog = DialogEditState(
            self.window,
            state_manager=self.window.state_manager,
            is_edit=False,
            parent_state=self.window.state_manager.get_root_state(),
        )
        dialog.edit_state_name.setText("ReviewState")
        dialog.show()
        self.app.processEvents()
        self.capture(
            dialog,
            workflow,
            "03-state-add-action.png",
            "model.state.add",
            "生产新增状态表单已填确定名称；此图不声称提交与 fresh reload 已通过",
        )
        dialog.close()

    def formulas(self):
        workflow = WORKFLOWS[9]
        root = self.window.state_manager.get_root_state()
        if root is None:
            raise RuntimeError("formula capture has no root state")

        transition = DialogAddTransition(
            self.window,
            self.window.state_manager,
            root,
            mutate_model=False,
        )
        transition.show()
        self.app.processEvents()
        transition.edit_condition.setText("count +")
        self.wait_formula(transition.condition_formula_editor, False)
        self.capture(
            transition,
            workflow,
            "00-guard-invalid.png",
            "formula.guard.invalid",
            "guard 使用生产 logical grammar 显示精确无效反馈并阻止提交",
        )
        transition.edit_condition.setText("count > 0 && count < 3")
        self.wait_formula(transition.condition_formula_editor, True)
        self.capture(
            transition,
            workflow,
            "01-guard-valid.png",
            "formula.guard.valid",
            "guard 合法 logical 表达式通过生产校验",
        )
        transition.edit_condition.clear()
        transition.edit_op.setPlainText("count = ;")
        self.wait_formula(transition.effect_formula_editor, False)
        self.capture(
            transition,
            workflow,
            "02-effect-invalid.png",
            "formula.effect.invalid",
            "effect 非法 assignment 显示位置与原因",
        )
        transition.edit_op.setPlainText("count = count + 1;")
        self.wait_formula(transition.effect_formula_editor, True)
        self.capture(
            transition,
            workflow,
            "03-effect-valid.png",
            "formula.effect.valid",
            "effect 合法 assignment 通过完整模型上下文校验",
        )
        transition.close()

        lifecycle = DialogAddLifecycle(
            self.window,
            self.window.state_manager,
            root,
            mutate_model=False,
        )
        lifecycle.show()
        lifecycle.edit_op.setPlainText("count = count + 1;\ncount = ;")
        self.wait_formula(lifecycle.lifecycle_formula_editor, False)
        self.capture(
            lifecycle,
            workflow,
            "04-lifecycle-invalid.png",
            "formula.lifecycle.invalid",
            "lifecycle 多行非法 action 标出第二行错误",
        )
        lifecycle.edit_op.setPlainText("count = count + 1;")
        self.wait_formula(lifecycle.lifecycle_formula_editor, True)
        self.capture(
            lifecycle,
            workflow,
            "05-lifecycle-valid.png",
            "formula.lifecycle.valid",
            "lifecycle 合法 action 使用生产 assembly 校验",
        )
        lifecycle.close()

        numeric = DialogNumericFormula(
            self.window,
            initial_text="1",
            revision_provider=lambda: self.window.document_session.source_revision,
            variable_definitions_provider=lambda: "def int count = 0;",
            debounce_ms=20,
        )
        numeric.show()
        numeric.input_field.setText("count > 0")
        self.wait_formula(numeric.formula_editor, False)
        self.capture(
            numeric,
            workflow,
            "06-numeric-invalid.png",
            "formula.numeric.invalid",
            "numeric 字段拒绝 logical 表达式且确定按钮禁用",
        )
        numeric.input_field.setText("count * 2 + 1")
        self.wait_formula(numeric.formula_editor, True)
        self.capture(
            numeric,
            workflow,
            "07-numeric-valid.png",
            "formula.numeric.valid",
            "numeric 合法表达式通过且确定按钮启用",
        )
        numeric.close()

    def graph(self):
        workflow = WORKFLOWS[2]
        self.window.action_show_graph.trigger()
        self.capture(
            self.window,
            workflow,
            "00-before.png",
            "graph.refresh",
            "Smetana 图形刷新前的图形工作区",
        )
        result = self.wait_with_running_capture(
            self.window.graph_task_finished,
            lambda: self.window.action_graph_gen.trigger(),
            lambda: self.capture(
                self.window,
                workflow,
                "02-running.png",
                "graph.refresh",
                "真实图形任务运行反馈",
            ),
        )[0]
        if result.status.value != "success":
            raise RuntimeError("graph capture failed: {}".format(result.error))
        self.capture(
            self.window,
            workflow,
            "03-result.png",
            "graph.refresh",
            "包含 Root/Idle/Running/Start 的真实 Smetana 状态图",
        )
        for offset, kind in enumerate(("plantuml", "png", "svg", "pdf"), 4):
            suffix = "puml" if kind == "plantuml" else kind
            target = self.runtime / "graph-{}.{}".format(kind, suffix)
            self.window.graph_panel.export_combo.setCurrentText(kind)
            self.choose_file_dialog(target)
            exported = _wait_signal(
                self.window.graph_task_finished,
                lambda: _press(self.window.graph_panel.export_button),
                timeout_ms=30000,
            )[0]
            if exported.status.value != "success" or not target.is_file():
                raise RuntimeError("graph {} export failed".format(kind))
            self.capture(
                self.window,
                workflow,
                "{:02d}-export-{}.png".format(offset, kind),
                "graph.export." + kind,
                "图形页真实导出 {} 后任务产物和 ready 图保持可见".format(kind),
            )

    def simulation(self):
        workflow = WORKFLOWS[3]
        panel = self.window.simulation_panel
        self.window.action_show_simulation.trigger()
        self.capture(
            self.window,
            workflow,
            "00-before.png",
            "simulation.initialize",
            "普通仿真未初始化状态",
        )
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.initialize_button),
        )
        self.capture(
            self.window,
            workflow,
            "01-action.png",
            "simulation.initialize",
            "初始化后的真实 runtime 快照",
        )
        panel.event_edit.setText("Start")
        _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.cycle_button),
        )
        self.capture(
            self.window,
            workflow,
            "03-result.png",
            "simulation.cycle",
            "执行 Start cycle 后的状态、变量和 transcript",
        )
        session = self.window._simulation_session
        if session is None:
            raise RuntimeError("simulation runtime disappeared after single cycle")
        runtime = session.runtime
        before_cycle = session.snapshot().cycle
        before_rows = panel.transcript_table.rowCount()
        panel.event_edit.clear()
        panel.cycle_count.setValue(10000)

        def start_and_pause():
            _press(panel.run_button)
            if not panel.pause_button.isEnabled():
                raise RuntimeError("continuous run did not expose pause")
            _press(panel.pause_button)

        paused_result = _wait_signal(
            self.window.simulation_task_finished,
            start_and_pause,
            timeout_ms=20000,
        )[0]
        if not paused_result.value.paused:
            raise RuntimeError("continuous simulation did not pause at a boundary")
        if self.window._simulation_session.runtime is not runtime:
            raise RuntimeError("pause replaced the simulation runtime")
        if session.snapshot().cycle <= before_cycle:
            raise RuntimeError("pause did not retain completed cycles")
        if panel.transcript_table.rowCount() <= before_rows:
            raise RuntimeError("pause did not retain transcript rows")
        if panel.status_label.text() != "已暂停":
            raise RuntimeError("paused status is not visible")
        if panel.run_button.text() != "继续运行":
            raise RuntimeError("paused state does not expose continue")
        paused_cycle = session.snapshot().cycle
        self.capture(
            self.window,
            workflow,
            "04-simulation-paused.png",
            "simulation.pause",
            "连续运行在 cycle 边界暂停，保留同一 runtime transcript 并显示继续运行",
        )

        panel.cycle_count.setValue(2)
        continued_result = _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.run_button),
        )[0]
        if continued_result.value.paused or continued_result.value.cancelled:
            raise RuntimeError("continued simulation did not complete normally")
        if self.window._simulation_session.runtime is not runtime:
            raise RuntimeError("continue replaced the simulation runtime")
        if session.snapshot().cycle <= paused_cycle:
            raise RuntimeError("continue did not advance the paused runtime")
        self.capture(
            self.window,
            workflow,
            "05-simulation-continued.png",
            "simulation.continue",
            "继续运行复用同一 runtime 并在原 transcript 后追加两个 cycle",
        )
        old_runtime = session.runtime
        reset_result = _wait_signal(
            self.window.simulation_task_finished,
            lambda: _press(panel.reset_button),
        )[0]
        if reset_result.status.value != "success" or session.runtime is old_runtime:
            raise RuntimeError("simulation reset did not replace the runtime")
        self.capture(
            self.window,
            workflow,
            "06-simulation-reset.png",
            "simulation.reset",
            "重置后使用新 runtime 回到初始状态并保留任务历史",
        )
        panel.event_edit.clear()
        panel.cycle_count.setValue(10000)

        def start_and_stop():
            _press(panel.run_button)
            if not panel.cancel_button.isEnabled():
                raise RuntimeError("continuous run did not expose stop")
            _press(panel.cancel_button)

        stopped = _wait_signal(
            self.window.simulation_task_finished,
            start_and_stop,
            timeout_ms=20000,
        )[0]
        if stopped.status.value != "cancelled" and not getattr(
            stopped.value, "cancelled", False
        ):
            raise RuntimeError("simulation stop did not cancel at a boundary")
        self.capture(
            self.window,
            workflow,
            "07-simulation-stopped.png",
            "simulation.stop",
            "停止连续仿真后显示已取消并保留已完成 cycle",
        )
        self.capture(
            self.window,
            workflow,
            "08-cancel-simulation.png",
            "cancel.simulation",
            "取消代表项使用真实停止按钮与协作 cycle 边界",
        )

    def dynamic_validation(self):
        workflow = WORKFLOWS[4]
        panel = self.window.dynamic_validation_panel
        self.window.action_show_dynamic_validation.trigger()
        self.capture(
            self.window,
            workflow,
            "00-before.png",
            "dynamic.suite",
            "运行内置验收前的场景工作区和术语声明",
        )
        result = self.wait_with_running_capture(
            self.window.dynamic_validation_finished,
            lambda: _press(panel.run_suite_button),
            lambda: self.capture(
                self.window,
                workflow,
                "02-running.png",
                "dynamic.suite",
                "四个内置用例执行中的真实反馈",
            ),
        )[0]
        if result.status.value != "success":
            raise RuntimeError("dynamic validation failed: {}".format(result.error))
        self.capture(
            self.window,
            workflow,
            "03-result.png",
            "dynamic.suite",
            "四用例 expected/actual 验收结果",
        )
        case_id = "design_validation_failure_multilevel_transition"
        resources = self.window.dynamic_validation_service.resource_dir
        model_source = resources / (case_id + ".fcstm")
        payload = json.loads((resources / (case_id + ".json")).read_text(encoding="utf-8"))
        model_target = self.runtime / model_source.name
        shutil.copy2(str(model_source), str(model_target))
        payload["case_id"] = "documentation_mutation"
        payload["steps"][-1]["expected"]["state"] = "Root.Mutated"
        mismatch_path = self.runtime / "dynamic-mismatch.json"
        mismatch_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        panel.scenario_edit.setText(str(mismatch_path))
        panel._update_actions()
        mismatch = _wait_signal(
            self.window.dynamic_validation_finished,
            lambda: _press(panel.run_user_button),
        )[0]
        mismatch_payload = json.loads(panel.report_json())
        mismatch_report = mismatch_payload.get("report", mismatch_payload)
        if mismatch.status.value != "success" or mismatch_report["status"] != "mismatch":
            raise RuntimeError("dynamic mutation did not produce mismatch")
        self.capture(
            self.window,
            workflow,
            "04-dynamic-mutation.png",
            "dynamic.mutation",
            "真实用户场景修改 expected 后显示不匹配和精确 diff",
        )
        payload["case_id"] = case_id
        payload["steps"][-1]["expected"]["state"] = "Root.A"
        pass_path = self.runtime / "dynamic-pass.json"
        pass_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        panel.scenario_edit.setText(str(pass_path))
        panel._update_actions()
        recovered = _wait_signal(
            self.window.dynamic_validation_finished,
            lambda: _press(panel.run_user_button),
        )[0]
        recovered_payload = json.loads(panel.report_json())
        recovered_report = recovered_payload.get("report", recovered_payload)
        if recovered.status.value != "success" or recovered_report["status"] != "passed":
            raise RuntimeError("dynamic mutation recovery did not pass")
        self.capture(
            self.window,
            workflow,
            "05-dynamic-recovered.png",
            "dynamic.recover",
            "恢复原 expected 后同一生产路径重新通过",
        )

    def generation(self):
        workflow = WORKFLOWS[5]
        templates = tuple(self.window.generation_service.list_templates())
        if len(templates) != 5:
            raise RuntimeError("expected five built-in templates")
        for index, descriptor in enumerate(templates):
            template_id = descriptor.name.replace("_", "-")
            dialog = DialogCodeGen(self.window, templates)
            dialog.generate_requested.connect(
                lambda request, current=dialog: self.window._start_generation(
                    request, current
                )
            )
            dialog.cancel_requested.connect(
                lambda: self.window._cancel_workspace_kind("code-generation")
            )
            dialog.language_combo.setCurrentIndex(0)
            template_index = dialog.template_combo.findData(descriptor.name)
            if template_index < 0:
                raise RuntimeError("template missing from dialog: " + descriptor.name)
            dialog.template_combo.setCurrentIndex(template_index)
            output = self.runtime / ("generated-" + descriptor.name)
            dialog.output_edit.setText(str(output))
            dialog.show()
            self.app.processEvents()
            if index == 0:
                self.capture(
                    dialog,
                    workflow,
                    "00-before.png",
                    "generation.templates",
                    "五模板生成对话框和模板来源选择",
                )
                self.capture(
                    dialog,
                    workflow,
                    "01-action.png",
                    "generation.{}".format(template_id),
                    "已选择模板与输出目录，尚未发布产物",
                )
            result = _wait_signal(
                self.window.generation_finished,
                lambda: _press(dialog.generate_button),
            )[0]
            if result.status.value != "success" or dialog.result_table.rowCount() < 1:
                raise RuntimeError("template generation failed: " + descriptor.name)
            self.capture(
                dialog,
                workflow,
                "03-result-{}.png".format(descriptor.name),
                "generation.{}".format(template_id),
                "{} 模板真实文件清单和 SHA-256".format(descriptor.title),
            )
            dialog.close()

        custom_template = self.runtime / "custom-template"
        custom_template.mkdir()
        (custom_template / "config.yaml").write_text("{}\n", encoding="utf-8")
        (custom_template / "hello.txt.j2").write_text(
            "root={{ model.root_state.name }}", encoding="utf-8"
        )
        custom = DialogCodeGen(self.window, templates)
        custom.generate_requested.connect(
            lambda request: self.window._start_generation(request, custom)
        )
        custom.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("code-generation")
        )
        custom.template_mode_combo.setCurrentIndex(1)
        custom.custom_template_edit.setText(str(custom_template))
        custom_output = self.runtime / "generated-custom"
        custom.output_edit.setText(str(custom_output))
        custom.show()
        self.app.processEvents()
        self.capture(
            custom,
            workflow,
            "04-custom-action.png",
            "generation.custom",
            "自定义模板模式选择真实 config.yaml 与 Jinja2 目录",
        )
        custom_result = _wait_signal(
            self.window.generation_finished,
            lambda: _press(custom.generate_button),
        )[0]
        custom_file = custom_output / "hello.txt"
        if (
            custom_result.status.value != "success"
            or not custom_file.is_file()
            or custom_file.read_text(encoding="utf-8") != "root=Root"
        ):
            raise RuntimeError("custom template did not generate root=Root")
        self.capture(
            custom,
            workflow,
            "05-custom-result.png",
            "generation.custom",
            "自定义模板真实生成非空 hello.txt 清单与 SHA",
        )
        custom.close()

    def unified_export(self):
        workflow = WORKFLOWS[6]
        dialog = DialogExport(self.window, dynamic_available=True)
        dialog.export_requested.connect(
            lambda request: self.window._start_unified_export(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self.window._cancel_workspace_kind("unified-export")
        )
        dialog.show()
        self.app.processEvents()
        self.capture(
            dialog,
            workflow,
            "00-before.png",
            "export.inspect-json",
            "统一导出单格式选择器",
        )
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("inspect-json"))
        target = self.runtime / "inspect-report.json"
        dialog.path_edit.setText(str(target))
        self.capture(
            dialog,
            workflow,
            "01-action.png",
            "export.inspect-json",
            "已选择 Inspect JSON 与目标文件",
        )
        result = _wait_signal(
            self.window.unified_export_finished,
            lambda: _press(dialog.start_button),
        )[0]
        if result.status.value != "success" or not target.is_file():
            raise RuntimeError("inspect JSON export failed")
        self.capture(
            dialog,
            workflow,
            "03-result.png",
            "export.inspect-json",
            "真实导出完成状态和字节数",
        )
        dialog.close()

        existing_target = self.runtime / "existing.fcstm"
        existing_target.write_text("old", encoding="utf-8")
        failed = DialogExport(self.window)
        failed.export_requested.connect(
            lambda request: self.window._start_unified_export(request, failed)
        )
        failed.path_edit.setText(str(existing_target))
        failed.show()
        failure = _wait_signal(
            self.window.unified_export_finished,
            lambda: _press(failed.start_button),
        )[0]
        if (
            failure.status.value != "failed"
            or existing_target.read_text(encoding="utf-8") != "old"
        ):
            raise RuntimeError("failed export did not preserve existing target")
        self.capture(
            failed,
            workflow,
            "04-failure-recovery.png",
            "export.existing-target",
            "已有目标拒绝覆盖，旧文件保持不变",
        )
        failed.close()

        export_specs = (
            ("fcstm", "dsl"),
            ("docx", "word"),
            ("xlsx", "excel"),
            ("plantuml", "plantuml"),
            ("png", "png"),
            ("svg", "svg"),
            ("pdf", "pdf"),
            ("dynamic-json", "dynamic-json"),
        )
        for offset, (kind, item_kind) in enumerate(export_specs, 5):
            current = DialogExport(self.window, dynamic_available=True)
            current.export_requested.connect(
                lambda request, active=current: self.window._start_unified_export(
                    request, active
                )
            )
            current.cancel_requested.connect(
                lambda: self.window._cancel_workspace_kind("unified-export")
            )
            current.kind_combo.setCurrentIndex(current.kind_combo.findData(kind))
            suffix = DialogExport.KIND_SUFFIXES[kind]
            export_target = self.runtime / "unified-{}.{}".format(kind, suffix)
            current.path_edit.setText(str(export_target))
            current.show()
            exported = _wait_signal(
                self.window.unified_export_finished,
                lambda active=current: _press(active.start_button),
                timeout_ms=30000,
            )[0]
            if exported.status.value != "success" or not export_target.is_file():
                raise RuntimeError("unified {} export failed".format(kind))
            self.capture(
                current,
                workflow,
                "{:02d}-result-{}.png".format(offset, kind),
                "export." + item_kind,
                "统一导出真实完成 {}，显示目标与非零字节数".format(kind),
            )
            current.close()

    def task_results(self):
        workflow = WORKFLOWS[7]
        dock = self.window.task_result_dock
        dock.hide()
        self.capture(
            self.window,
            workflow,
            "00-before.png",
            "tasks.history",
            "成功任务不强制展开任务 dock",
        )
        dock.show()
        dock.refresh()
        dock.table.clearSelection()
        dock.detail.clear()
        dock.artifact_list.clear()
        self.app.processEvents()
        self.capture(
            self.window,
            workflow,
            "01-action.png",
            "tasks.history",
            "用户主动打开任务历史与脱敏搜索",
        )
        if dock.table.rowCount() < 8:
            raise RuntimeError("task history is incomplete")
        dock.table.setCurrentCell(0, 0)
        dock.table.selectRow(0)
        self.capture(
            self.window,
            workflow,
            "03-result.png",
            "tasks.history",
            "真实任务详情和产物入口",
        )
        failed_index = dock.status_filter.findData("failed")
        if failed_index >= 0:
            dock.status_filter.setCurrentIndex(failed_index)
            dock.refresh()
        self.capture(
            self.window,
            workflow,
            "04-failure-recovery.png",
            "tasks.failure-filter",
            "失败筛选保留可重试详情且路径默认脱敏",
        )
        before_records = len(self.window.task_center.records)
        self.confirm_message_box(QtWidgets.QMessageBox.Yes)
        _press(dock.clear_completed_button)
        after_completed = len(self.window.task_center.records)
        if after_completed >= before_records:
            raise RuntimeError("clear completed did not remove successful history")
        if not any(record.status.value == "failed" for record in self.window.task_center.records):
            raise RuntimeError("clear completed removed the failed recovery record")
        dock.status_filter.setCurrentIndex(0)
        dock.refresh()
        self.capture(
            self.window,
            workflow,
            "05-clear-completed.png",
            "tasks.clear-completed",
            "清空已完成只删除成功记录并保留失败项",
        )
        self.confirm_message_box(QtWidgets.QMessageBox.Yes)
        _press(dock.clear_all_button)
        dock.refresh()
        if any(
            record.boundary.value == "explicit"
            and record.status.value not in ("running", "queued", "cancel_requested")
            for record in self.window.task_center.records
        ):
            raise RuntimeError("clear all left terminal persistent history")
        self.capture(
            self.window,
            workflow,
            "06-clear-all.png",
            "tasks.clear-all",
            "清空历史删除全部终态持久记录且不伪造成功任务",
        )

    def dirty_branches(self):
        workflow = WORKFLOWS[10]
        editor = self.window.source_editor
        self.window.action_show_source.trigger()
        _wait_signal(
            self.window.document_validation_finished,
            lambda: _keyboard_replace(editor, _SOURCE + "\n"),
            accept=self.driver._is_current_validation,
        )
        if not self.window.document_session.dirty:
            raise RuntimeError("dirty fixture did not become dirty")
        self.confirm_message_box(QtWidgets.QMessageBox.Save)
        if not self.window._confirm_document_replacement():
            raise RuntimeError("dirty Save branch was rejected")
        if self.window.document_session.dirty:
            raise RuntimeError("dirty Save branch did not save")
        self.capture(
            self.window,
            workflow,
            "00-dirty-save.png",
            "dirty.save",
            "真实未保存确认框选择 Save 后磁盘和 session 转为已保存",
        )

        _wait_signal(
            self.window.document_validation_finished,
            lambda: _keyboard_replace(editor, _SOURCE),
            accept=self.driver._is_current_validation,
        )
        self.confirm_message_box(QtWidgets.QMessageBox.Cancel)
        if self.window._confirm_document_replacement():
            raise RuntimeError("dirty Cancel branch allowed replacement")
        if not self.window.document_session.dirty or editor.toPlainText() != _SOURCE:
            raise RuntimeError("dirty Cancel branch changed the current session")
        self.capture(
            self.window,
            workflow,
            "01-dirty-cancel.png",
            "dirty.cancel",
            "真实未保存确认框选择 Cancel 后 session、dirty 与源码保持",
        )

        other = self.runtime / "dirty-other.fcstm"
        other.write_text("state Other;\n", encoding="utf-8")

        def discard_and_load():
            self.confirm_message_box(QtWidgets.QMessageBox.Discard)
            if not self.window._confirm_document_replacement():
                raise RuntimeError("dirty Discard branch was rejected")
            self.window._start_document_load(str(other))

        discarded = _wait_signal(
            self.window.document_load_finished,
            discard_and_load,
        )[0]
        if discarded.status.value != "success" or "state Other" not in self.window.source_editor.toPlainText():
            raise RuntimeError("dirty Discard branch did not load the target")
        self.capture(
            self.window,
            workflow,
            "02-dirty-discard.png",
            "dirty.discard",
            "真实未保存确认框选择 Discard 后不写旧编辑并加载目标",
        )
        self.driver.source_path.write_text(_SOURCE, encoding="utf-8")
        restored = _wait_signal(
            self.window.document_load_finished,
            lambda: self.window._start_document_load(str(self.driver.source_path)),
        )[0]
        if restored.status.value != "success":
            raise RuntimeError("failed to restore primary fixture after dirty branches")

    def stale_graph(self):
        workflow = WORKFLOWS[10]
        self.window.action_show_graph.trigger()
        editor = self.window.source_editor

        def start_then_edit():
            _press(self.window.graph_panel.refresh_button)
            _keyboard_replace(editor, _SOURCE + "\n")

        result = _wait_signal(
            self.window.graph_task_finished,
            start_then_edit,
            timeout_ms=30000,
        )[0]
        if result.status.value != "stale":
            raise RuntimeError(
                "graph stale boundary was not observable (status {})".format(
                    result.status.value
                )
            )
        self.window.action_show_graph.trigger()
        self.capture(
            self.window,
            workflow,
            "03-stale-graph.png",
            "stale.graph",
            "图形任务完成前 revision 改变，旧结果标记 stale 且未发布",
        )
        _wait_signal(
            self.window.document_validation_finished,
            lambda: _keyboard_replace(editor, _SOURCE),
            accept=self.driver._is_current_validation,
        )

    def run(self):
        self.prepare()
        try:
            self.open_document()
            self.diagnostics()
            self.model_crud()
            self.formulas()
            self.graph()
            self.simulation()
            self.dynamic_validation()
            self.generation()
            self.unified_export()
            self.dirty_branches()
            self.stale_graph()
            self.task_results()
            self.write_manifest()
        finally:
            self.driver.close()
            shutil.rmtree(str(self.runtime), ignore_errors=True)

    def write_manifest(self):
        source = _source_identity()
        payload = {
            "schema": "fcstm-gui.workflow-images",
            "version": 1,
            "evidence_kind": "source-reference",
            "fresh_release_evidence": False,
            "statement": (
                "源码态操作手册参考图；不得替代 fresh onedir/onefile 最终证据。"
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "capture": {
                "platform": platform.system().lower(),
                "platform_detail": platform.platform(),
                "machine": platform.machine(),
                "viewport": "{}x{}".format(*self.viewport),
                "scale": self.scale,
                "qt_platform": self.app.platformName(),
                "font_family": self.app.font().family(),
                "font_point_size": self.app.font().pointSize(),
            },
            "manual_review": {
                "status": "pending",
                "reviewer": None,
                "reviewed_at": None,
                "findings": [],
            },
            "acceptance_aliases": SOURCE_REFERENCE_ALIASES,
            "images": self.images,
        }
        target = self.output / "manifest.json"
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


def _git_output(*args):
    return subprocess.check_output(
        ("git",) + args, cwd=str(ROOT), universal_newlines=True
    ).strip()


def _source_identity():
    status = _git_output("status", "--porcelain")
    patch = subprocess.check_output(
        ("git", "diff", "--binary", "HEAD"), cwd=str(ROOT)
    )
    return {
        "commit": _git_output("rev-parse", "HEAD"),
        "tree_sha": _git_output("rev-parse", "HEAD^{tree}"),
        "worktree_dirty": bool(status),
        "worktree_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "source_content_sha256": _source_content_sha256(),
    }


def _source_content_sha256():
    paths = _git_output(
        "ls-files",
        "-co",
        "--exclude-standard",
        "--",
        "app",
        "main.py",
        "main.spec",
        "requirements*.txt",
    ).splitlines()
    digest = hashlib.sha256()
    for relative in sorted(item for item in paths if item):
        path = ROOT / relative
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _parse_viewport(value):
    width, height = value.lower().split("x", 1)
    return int(width), int(height)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--viewport", default="1280x720")
    parser.add_argument("--scale", default=os.environ.get("QT_SCALE_FACTOR", "1"))
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_SCALE_FACTOR", str(args.scale))
    capture = WorkflowCapture(args.output, _parse_viewport(args.viewport), args.scale)
    capture.run()
    print("captured {} workflow images -> {}".format(len(capture.images), capture.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
