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
    sat_solver = z3.Solver()
    sat_solver.add(value > 5, value < 10)
    if sat_solver.check() != z3.sat or not 5 < sat_solver.model()[value].as_long() < 10:
        raise RuntimeError('Z3 integer SAT/model check failed')

    unsat_solver = z3.Solver()
    unsat_solver.add(value > 2, value < 2)
    if unsat_solver.check() != z3.unsat:
        raise RuntimeError('Z3 UNSAT check failed')

    real = z3.Real('fcstm_real')
    real_solver = z3.Solver()
    real_solver.add(real * 3 == 1)
    if real_solver.check() != z3.sat or str(real_solver.model()[real]) != '1/3':
        raise RuntimeError('Z3 real arithmetic check failed')

    bits = z3.BitVec('fcstm_bits', 8)
    bit_solver = z3.Solver()
    bit_solver.add((bits & 0x0f) == 0x0a, bits == 0x2a)
    if bit_solver.check() != z3.sat or bit_solver.model()[bits].as_long() != 0x2a:
        raise RuntimeError('Z3 bit-vector check failed')

    optimum = z3.Int('fcstm_optimum')
    optimizer = z3.Optimize()
    optimizer.add(optimum >= 0, optimum <= 20)
    optimizer.maximize(optimum)
    if optimizer.check() != z3.sat or optimizer.model()[optimum].as_long() != 20:
        raise RuntimeError('Z3 Optimize/maximize check failed')
    return '5 solve scenarios OK (z3 {})'.format(z3.get_version_string())


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


_ACCEPTANCE_DSL = 'state Smoke { state Idle; [*] -> Idle; Idle -> [*]; }'


def _invoke_pyfcstm(arguments, files=None):
    from click.testing import CliRunner
    from pyfcstm.entry.cli import cli
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open('acceptance.fcstm', 'w') as file:
            file.write(_ACCEPTANCE_DSL)
        result = runner.invoke(cli, arguments)
        if result.exit_code != 0:
            raise RuntimeError('pyfcstm {} failed: {}'.format(' '.join(arguments), result.output[-1000:]))
        outputs = {}
        for path in files or ():
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise RuntimeError('pyfcstm did not create non-empty ' + path)
            with open(path, 'rb') as file:
                outputs[path] = file.read()
        return result.output, outputs


def _check_invalid_diagnostics():
    from click.testing import CliRunner
    from pyfcstm.entry.cli import cli
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open('invalid.fcstm', 'w') as file:
            file.write('state Broken { state ; }')
        result = runner.invoke(cli, ['inspect', '-i', 'invalid.fcstm', '--format', 'json'])
        if result.exit_code == 0 or not any(token in result.output.lower() for token in ('line', 'column', 'syntax', 'error')):
            raise RuntimeError('invalid DSL did not produce positional diagnostics: ' + result.output[-500:])
        return 'rejected with diagnostic output'


def _check_inspect(format_name):
    output, _ = _invoke_pyfcstm(['inspect', '-i', 'acceptance.fcstm', '--format', format_name, '--color', 'never'])
    if 'Smoke' not in output:
        raise RuntimeError(format_name + ' inspect omitted machine name')
    return '{} chars'.format(len(output))


def _check_template(template_name):
    from click.testing import CliRunner
    from pyfcstm.entry.cli import cli
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open('acceptance.fcstm', 'w') as file:
            file.write(_ACCEPTANCE_DSL)
        result = runner.invoke(cli, ['generate', '-i', 'acceptance.fcstm', '--template', template_name,
                                     '-o', 'generated', '--clear'])
        if result.exit_code != 0:
            raise RuntimeError(template_name + ' generation failed: ' + result.output[-1000:])
        generated = []
        for root, _, names in os.walk('generated'):
            generated.extend(os.path.join(root, name) for name in names if os.path.getsize(os.path.join(root, name)) > 0)
        if not generated:
            raise RuntimeError(template_name + ' template produced no non-empty files')
        return '{} files'.format(len(generated))


def _check_pyfcstm_plantuml_cli():
    _, outputs = _invoke_pyfcstm(['plantuml', '-i', 'acceptance.fcstm', '-o', 'machine.puml'], ['machine.puml'])
    if b'@startuml' not in outputs['machine.puml']:
        raise RuntimeError('plantuml CLI output is invalid')
    return '{} bytes'.format(len(outputs['machine.puml']))


def _check_visualize(format_name):
    output_name = 'machine.' + format_name
    _, outputs = _invoke_pyfcstm(['visualize', '-i', 'acceptance.fcstm', '-o', output_name,
                                 '--type', format_name, '--renderer', 'local',
                                 '--plantuml-jar', _plantuml_path(), '--no-open'], [output_name])
    magic = {'png': b'\x89PNG', 'svg': b'<?xml', 'pdf': b'%PDF'}[format_name]
    if not outputs[output_name].startswith(magic):
        raise RuntimeError(format_name + ' visualization has incorrect magic')
    return '{} bytes'.format(len(outputs[output_name]))


def _check_simulate_cli():
    output, _ = _invoke_pyfcstm(['simulate', '-i', 'acceptance.fcstm', '--execute', 'current', '--no-color'])
    if 'Idle' not in output and 'Smoke' not in output:
        raise RuntimeError('batch simulation produced no state output: ' + output[-500:])
    return '{} chars'.format(len(output))


def _check_pygments_highlight():
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pyfcstm.highlight.pygments_lexer import FcstmLexer
    output = highlight(_ACCEPTANCE_DSL, FcstmLexer(), HtmlFormatter())
    if 'Smoke' not in output or '<span' not in output:
        raise RuntimeError('FCSTM Pygments highlighting failed')
    return '{} HTML chars'.format(len(output))


def _checks():
    checks = [('python runtime', _check_python)]
    for name in ('PyQt5', 'qtpy', 'qtawesome', 'qtmodern', 'openpyxl', 'docx', 'pyfcstm'):
        checks.append(('import ' + name, lambda name=name: _check_import(name)))
    checks.extend([('java executable', _check_java), ('plantuml.jar', _check_plantuml_jar),
                   ('pyfcstm DSL/model/PlantUML roundtrip', _check_pyfcstm_roundtrip),
                   ('pyfcstm simulation runtime', _check_pyfcstm_simulation),
                   ('pyfcstm invalid syntax diagnostics', _check_invalid_diagnostics),
                   ('pyfcstm inspect human', lambda: _check_inspect('human')),
                   ('pyfcstm inspect json', lambda: _check_inspect('json')),
                   ('pyfcstm PlantUML CLI', _check_pyfcstm_plantuml_cli),
                   ('pyfcstm visualize PNG', lambda: _check_visualize('png')),
                   ('pyfcstm visualize SVG', lambda: _check_visualize('svg')),
                   ('pyfcstm visualize PDF', lambda: _check_visualize('pdf')),
                   ('pyfcstm batch simulation CLI', _check_simulate_cli),
                   ('pyfcstm Pygments highlighting', _check_pygments_highlight),
                   ('Z3 SAT solver', _check_z3_solver),
                   ('Qt application', _check_qt_application),
                   ('Qt native widgets and assets', _check_qt_native_widgets),
                   ('XLSX and DOCX roundtrips', _check_office_roundtrips),
                   ('PlantUML Java PNG render', _check_plantuml_render),
                   ('main GUI window lifecycle', _check_main_window)])
    for template_name in ('python', 'c', 'c_poll', 'cpp', 'cpp_poll'):
        checks.append(('pyfcstm generate template ' + template_name,
                       lambda template_name=template_name: _check_template(template_name)))
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
