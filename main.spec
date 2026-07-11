# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

mode = os.environ.get('FCSTM_GUI_BUILD_MODE', 'onedir').lower()
datas = [('docs/plantuml.jar', 'docs')] + collect_data_files('qtawesome') + collect_data_files('pyfcstm')
binaries = collect_dynamic_libs('z3', destdir='z3/lib')

# Qt's excluded GL/X11 entry points are bundled so the fresh Linux verifier
# needs only xvfb and Java, matching the distributable contract.
if sys.platform == 'linux':
    for name in ('libGL.so.1', 'libGLdispatch.so.0', 'libGLX.so.0', 'libX11.so.6',
                 'libX11-xcb.so.1', 'libXext.so.6', 'libxcb.so.1', 'libXau.so.6',
                 'libXdmcp.so.6', 'libbsd.so.0'):
        for directory in ('/usr/lib/x86_64-linux-gnu', '/lib/x86_64-linux-gnu', '/usr/lib64'):
            path = os.path.join(directory, name)
            if os.path.exists(path):
                binaries.append((path, '.'))
                break
hiddenimports = collect_submodules('app') + collect_submodules('pyfcstm') + ['ipaddress']
a = Analysis(['main.py'], pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, [] if mode == 'onedir' else a.binaries,
          [] if mode == 'onedir' else a.zipfiles, [] if mode == 'onedir' else a.datas,
          name='fcstm-gui', debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=True, exclude_binaries=(mode == 'onedir'))
if mode == 'onedir':
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='fcstm-gui')
