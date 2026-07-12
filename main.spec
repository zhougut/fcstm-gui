# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import shutil
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

mode = os.environ.get('FCSTM_GUI_BUILD_MODE', 'onedir').lower()
datas = [
    ('docs/plantuml.jar', 'docs'),
    (
        'app/resources/self_check/dynamic_validation',
        'app/resources/self_check/dynamic_validation',
    ),
    (
        'app/resources/self_check/self_check_report.schema.json',
        'app/resources/self_check',
    ),
    (
        'app/resources/self_check/acceptance_check_report.schema.json',
        'app/resources/self_check',
    ),
] + collect_data_files('qtawesome') + collect_data_files('pyfcstm')
if sys.platform == 'win32':
    z3_suffixes = ('.dll',)
elif sys.platform == 'darwin':
    z3_suffixes = ('.dylib',)
else:
    z3_suffixes = ('.so',)
binaries = [item for item in collect_dynamic_libs('z3', destdir='z3/lib')
            if item[0].lower().endswith(z3_suffixes)]

if sys.platform == 'win32':
    cairo = shutil.which('libcairo-2.dll')
    if cairo:
        cairo_dir = os.path.dirname(cairo)
        cairo_runtime = (
            'libcairo-2.dll', 'libpixman-1-0.dll', 'libfontconfig-1.dll', 'libfreetype-6.dll',
            'libpng16-16.dll', 'zlib1.dll', 'libbz2-1.dll', 'libbrotlidec.dll',
            'libbrotlicommon.dll', 'libexpat-1.dll', 'libglib-2.0-0.dll', 'libintl-8.dll',
            'libiconv-2.dll', 'libpcre2-8-0.dll', 'libffi-8.dll', 'libharfbuzz-0.dll',
            'libgraphite2.dll', 'libwinpthread-1.dll', 'libgcc_s_seh-1.dll', 'libstdc++-6.dll',
        )
        binaries += [(os.path.join(cairo_dir, name), '.') for name in cairo_runtime
                     if os.path.isfile(os.path.join(cairo_dir, name))]

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
