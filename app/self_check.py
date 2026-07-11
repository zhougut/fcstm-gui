"""Fault-tolerant command-line diagnostics used by users and packaged builds."""
from __future__ import print_function
import importlib
import os
import platform
import pkgutil
import shutil
import sys
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


def _checks():
    checks = [('python runtime', _check_python)]
    for name in ('PyQt5', 'qtpy', 'qtawesome', 'qtmodern', 'openpyxl', 'docx', 'pyfcstm'):
        checks.append(('import ' + name, lambda name=name: _check_import(name)))
    checks.extend([('java executable', _check_java), ('plantuml.jar', _check_plantuml_jar),
                   ('pyfcstm DSL/model/PlantUML roundtrip', _check_pyfcstm_roundtrip),
                   ('Z3 SAT solver', _check_z3_solver),
                   ('Qt application', _check_qt_application),
                   ('GUI module import', lambda: _check_import('app.widget.main_window'))])
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
