"""Application entry point and dependency-safe diagnostic dispatcher."""
import os
import sys
import traceback


def _configure_frozen_qt_plugins():
    """Point a frozen build at its own Qt plugins, not a host Python install."""
    if not getattr(sys, 'frozen', False):
        return
    bundle_root = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    candidates = (
        os.path.join(bundle_root, 'PyQt5', 'Qt5', 'plugins'),
        os.path.join(bundle_root, 'PyQt5', 'Qt', 'plugins'),
        os.path.join(bundle_root, '_internal', 'PyQt5', 'Qt5', 'plugins'),
        os.path.join(os.path.dirname(sys.executable), 'PyQt5', 'Qt5', 'plugins'),
        os.path.join(os.path.dirname(sys.executable), '_internal', 'PyQt5', 'Qt5', 'plugins'),
    )
    for plugin_root in candidates:
        platforms = os.path.join(plugin_root, 'platforms')
        if os.path.isdir(platforms):
            # Always replace inherited values.  Anaconda, Qt Creator and other
            # Qt applications commonly leave these variables pointing at an
            # incompatible plugin tree, which makes an otherwise complete EXE
            # fail before the main window appears.
            os.environ['QT_PLUGIN_PATH'] = plugin_root
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = platforms
            return


def _diagnostic_requested():
    return os.environ.get('FCSTM_GUI_SELF_CHECK') == '1' or '--self-check' in sys.argv[1:] or '--smoke-test' in sys.argv[1:]


def _acceptance_requested():
    return '--acceptance-check' in sys.argv[1:]


def _option_value(name):
    arguments = sys.argv[1:]
    try:
        index = arguments.index(name)
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        raise ValueError(name + ' requires a value')
    return arguments[index + 1]


def _run_diagnostic():
    try:
        from app.self_check import run_self_check
        return run_self_check(json_report=_option_value('--json-report'))
    except BaseException as exc:
        print('\033[1;31mfcstm-gui self-check: bootstrap failure: {!r}\033[0m'.format(exc), flush=True)
        traceback.print_exc()
        return 2


def _run_acceptance():
    try:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from app.acceptance_check import run_acceptance_check
        return run_acceptance_check(
            json_report=_option_value('--json-report'),
            artifact_dir=_option_value('--artifact-dir'),
            viewport=_option_value('--viewport') or '1280x720',
        )
    except BaseException as exc:
        print('\033[1;31mfcstm-gui acceptance-check: bootstrap failure: {!r}\033[0m'.format(exc), flush=True)
        traceback.print_exc()
        return 2


if __name__ == '__main__':
    _configure_frozen_qt_plugins()
    if _acceptance_requested():
        sys.exit(_run_acceptance())
    if _diagnostic_requested():
        sys.exit(_run_diagnostic())
    from app import run_app
    run_app()
