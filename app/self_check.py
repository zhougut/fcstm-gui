"""Fault-tolerant command-line diagnostics used by users and packaged builds."""
from __future__ import print_function
import importlib
import os
import platform
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


def _checks():
    checks = [('python runtime', _check_python)]
    for name in ('PyQt5', 'qtpy', 'qtawesome', 'qtmodern', 'openpyxl', 'docx', 'pyfcstm'):
        checks.append(('import ' + name, lambda name=name: _check_import(name)))
    checks.extend([('java executable', _check_java), ('plantuml.jar', _check_plantuml_jar),
                   ('Qt application', _check_qt_application),
                   ('GUI module import', lambda: _check_import('app.widget.main_window'))])
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
