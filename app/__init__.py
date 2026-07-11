"""Public application API with dependency-safe lazy loading."""


def run_app(*args, **kwargs):
    from .app import run_app as _run_app
    return _run_app(*args, **kwargs)
