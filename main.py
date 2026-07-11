"""Application entry point and dependency-safe diagnostic dispatcher."""
import os
import sys
import traceback


def _diagnostic_requested():
    return os.environ.get('FCSTM_GUI_SELF_CHECK') == '1' or '--self-check' in sys.argv[1:] or '--smoke-test' in sys.argv[1:]


def _run_diagnostic():
    try:
        from app.self_check import run_self_check
        return run_self_check()
    except BaseException as exc:
        print('\033[1;31mfcstm-gui self-check: bootstrap failure: {!r}\033[0m'.format(exc), flush=True)
        traceback.print_exc()
        return 2


if __name__ == '__main__':
    if _diagnostic_requested():
        sys.exit(_run_diagnostic())
    from app import run_app
    run_app()
