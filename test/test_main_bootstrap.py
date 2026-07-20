import os

import main


def test_frozen_bootstrap_replaces_inherited_qt_plugin_paths(tmp_path, monkeypatch):
    plugin_root = tmp_path / "PyQt5" / "Qt5" / "plugins"
    platform_root = plugin_root / "platforms"
    platform_root.mkdir(parents=True)
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", "C:/host/Qt/plugins")
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "C:/host/Qt/plugins/platforms")

    main._configure_frozen_qt_plugins()

    assert os.environ["QT_PLUGIN_PATH"] == str(plugin_root)
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == str(platform_root)


def test_source_bootstrap_preserves_developer_qt_environment(monkeypatch):
    monkeypatch.delattr(main.sys, "frozen", raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", "C:/developer/Qt/plugins")

    main._configure_frozen_qt_plugins()

    assert os.environ["QT_PLUGIN_PATH"] == "C:/developer/Qt/plugins"
