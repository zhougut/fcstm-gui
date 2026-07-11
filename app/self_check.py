"""Fault-tolerant command-line diagnostics used by users and packaged builds."""
from __future__ import print_function
import importlib
import os
import platform
import pkgutil
import shutil
import subprocess
import sys
import tempfile
import traceback

RESET = '\033[0m'
BOLD = '\033[1m'
GREEN = '\033[32m'
RED = '\033[31m'
CYAN = '\033[36m'


def _color(code, text):
    return code + text + RESET


def _check_python():
    if sys.version_info[:2] < (3, 7):
        raise RuntimeError('Python 3.7 or newer is required')
    return platform.python_version()


def _check_import(name):
    module = importlib.import_module(name)
    return getattr(module, '__version__', 'imported')


def _check_java():
    path = shutil.which('java')
    if not path:
        raise RuntimeError('java is not on PATH (PlantUML rendering will be unavailable)')
    return path


def _check_plantuml_jar():
    roots = [getattr(sys, '_MEIPASS', ''), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for root in roots:
        path = os.path.join(root, 'docs', 'plantuml.jar') if root else ''
        if path and os.path.isfile(path):
            return path
    raise RuntimeError('docs/plantuml.jar is missing')


def _check_qt_application():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.processEvents()
    return 'event processing OK'


def _pyfcstm_module_names():
    import pyfcstm
    names = []
    for module in pkgutil.walk_packages(pyfcstm.__path__, pyfcstm.__name__ + '.'):
        # Command entry points parse argv when executed and are covered by
        # their underlying libraries instead of being imported as scripts.
        if not module.name.endswith('.__main__'):
            names.append(module.name)
    return sorted(names)


def _check_pyfcstm_roundtrip():
    from pyfcstm.dsl import parse_with_grammar_entry
    from pyfcstm.model import parse_dsl_node_to_state_machine
    source = 'state Smoke { state Idle; [*] -> Idle; Idle -> [*]; }'
    ast_node = parse_with_grammar_entry(source, entry_name='state_machine_dsl')
    machine = parse_dsl_node_to_state_machine(ast_node)
    ast_text = str(machine.to_ast_node())
    plantuml = machine.to_plantuml()
    if machine.root_state.name != 'Smoke' or 'state Smoke' not in ast_text or '@startuml' not in plantuml:
        raise RuntimeError('pyfcstm roundtrip returned incomplete output')
    return '{} AST chars, {} PlantUML chars'.format(len(ast_text), len(plantuml))


def _check_z3_solver():
    import z3
    value = z3.Int('fcstm_self_check')
    solver = z3.Solver()
    solver.add(value == 7)
    if solver.check() != z3.sat or solver.model()[value].as_long() != 7:
        raise RuntimeError('Z3 failed the SAT/model check')
    return z3.get_version_string()


def _check_qt_native_widgets():
    from PyQt5.Qsci import QsciScintilla
    from PyQt5.QtWidgets import QApplication
    import qtawesome
    import qtmodern.styles
    app = QApplication.instance() or QApplication([])
    editor = QsciScintilla()
    editor.setText('state Smoke;')
    icon = qtawesome.icon('fa5s.check')
    qtmodern.styles.dark(app)
    editor.show()
    app.processEvents()
    if editor.text() != 'state Smoke;' or icon.isNull():
        raise RuntimeError('Qt native widget/font integration failed')
    editor.close()
    return 'QScintilla + qtawesome + qtmodern OK'


def _check_office_roundtrips():
    from io import BytesIO
    from docx import Document
    from openpyxl import Workbook, load_workbook
    xlsx = BytesIO()
    workbook = Workbook()
    workbook.active['A1'] = 'fcstm'
    workbook.save(xlsx)
    xlsx.seek(0)
    if load_workbook(xlsx).active['A1'].value != 'fcstm':
        raise RuntimeError('openpyxl XLSX roundtrip failed')
    docx = BytesIO()
    document = Document()
    document.add_paragraph('fcstm')
    document.save(docx)
    docx.seek(0)
    if Document(docx).paragraphs[0].text != 'fcstm':
        raise RuntimeError('python-docx roundtrip failed')
    return '{} XLSX bytes, {} DOCX bytes'.format(len(xlsx.getvalue()), len(docx.getvalue()))


def _plantuml_path():
    roots = [getattr(sys, '_MEIPASS', ''), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for root in roots:
        path = os.path.join(root, 'docs', 'plantuml.jar') if root else ''
        if path and os.path.isfile(path):
            return path
    raise RuntimeError('docs/plantuml.jar is missing')


def _check_plantuml_render():
    java = shutil.which('java')
    if not java:
        raise RuntimeError('java is not on PATH')
    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, 'smoke.puml')
        with open(source, 'w') as file:
            file.write('@startuml\n[*] --> Ready\n@enduml\n')
        process = subprocess.run([java, '-jar', _plantuml_path(), '-tpng', source],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        output = os.path.join(directory, 'smoke.png')
        if process.returncode != 0 or not os.path.isfile(output) or os.path.getsize(output) < 100:
            raise RuntimeError('PlantUML PNG render failed: {!r}'.format(process.stderr[-500:]))
        return '{} PNG bytes'.format(os.path.getsize(output))


def _check_pyfcstm_simulation():
    from pyfcstm.dsl import parse_with_grammar_entry
    from pyfcstm.model import parse_dsl_node_to_state_machine
    from pyfcstm.simulate import SimulationRuntime
    source = 'state Smoke { state Idle; [*] -> Idle; Idle -> [*]; }'
    machine = parse_dsl_node_to_state_machine(parse_with_grammar_entry(source, entry_name='state_machine_dsl'))
    runtime = SimulationRuntime(machine)
    return type(runtime).__name__ + ' constructed'


def _check_main_window():
    from PyQt5.QtWidgets import QApplication
    from app.widget import AppMainWindow
    app = QApplication.instance() or QApplication([])
    window = AppMainWindow()
    window.show()
    app.processEvents()
    if not window.isVisible():
        raise RuntimeError('main window did not become visible')
    window.close()
    return 'constructed, shown, events processed, closed'


def _checks():
    checks = [('python runtime', _check_python)]
    for name in ('PyQt5', 'qtpy', 'qtawesome', 'qtmodern', 'openpyxl', 'docx', 'pyfcstm'):
        checks.append(('import ' + name, lambda name=name: _check_import(name)))
    checks.extend([('java executable', _check_java), ('plantuml.jar', _check_plantuml_jar),
                   ('pyfcstm DSL/model/PlantUML roundtrip', _check_pyfcstm_roundtrip),
                   ('pyfcstm simulation runtime', _check_pyfcstm_simulation),
                   ('Z3 SAT solver', _check_z3_solver),
                   ('Qt application', _check_qt_application),
                   ('Qt native widgets and assets', _check_qt_native_widgets),
                   ('XLSX and DOCX roundtrips', _check_office_roundtrips),
                   ('PlantUML Java PNG render', _check_plantuml_render),
                   ('main GUI window lifecycle', _check_main_window)])
    try:
        module_names = _pyfcstm_module_names()
    except BaseException as exc:
        checks.append(('discover pyfcstm modules', lambda exc=exc: (_ for _ in ()).throw(exc)))
    else:
        for name in module_names:
            checks.append(('import ' + name, lambda name=name: _check_import(name)))
    return checks


def run_self_check():
    try:
        if os.name == 'nt':
            import colorama
            colorama.just_fix_windows_console()
    except BaseException:
        pass
    results = []
    try:
        checks = _checks()
    except BaseException as exc:
        checks = []
        results.append(('check discovery', False, repr(exc)))
    print(_color(CYAN, 'fcstm-gui self-check: running {} checks'.format(len(checks))))
    for index, (name, check) in enumerate(checks, 1):
        try:
            detail = check()
            results.append((name, True, str(detail)))
            print('[{:02d}/{:02d}] {}: {} ({})'.format(index, len(checks), name, _color(GREEN, 'OK'), detail))
        except BaseException as exc:
            results.append((name, False, repr(exc)))
            print('[{:02d}/{:02d}] {}: {} ({!r})'.format(index, len(checks), name, _color(RED, 'FAIL'), exc))
            traceback.print_exc()
    failures = [item for item in results if not item[1]]
    passed = len(results) - len(failures)
    status = _color(GREEN if not failures else RED, 'PASSED' if not failures else 'FAILED')
    print(_color(CYAN, 'fcstm-gui self-check:') + ' {} OK / {} FAIL - {}'.format(passed, len(failures), BOLD + status + RESET))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(run_self_check())
