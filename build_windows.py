r"""Build a per-user Windows installer with bundled Python (developer machine only).

Usage from Windows: C:\Python313\python.exe build_windows.py
The resulting release/ProgramFlow-Setup-0.2.6-x64.exe needs no Python or WSL
on the user's machine. Build tools and wheels live under .build/, not in the
installed application or its encrypted user data directory.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / '.build'
VENV = BUILD / 'venv'
PYTHON = VENV / 'Scripts' / 'python.exe'


def run(args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def copy_dependency_licenses(destination):
    """Retain notices for the bundled interpreter and third-party wheels."""
    import importlib.metadata

    notices = destination / 'THIRD_PARTY_LICENSES'
    notices.mkdir(exist_ok=True)
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get('Name', 'unknown')
        for entry in distribution.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in entry.parts):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    target = notices / name / Path(*entry.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    for base in (Path(sys.base_prefix), Path(sys.executable).parent):
        license_file = base / 'LICENSE.txt'
        if license_file.is_file():
            shutil.copy2(license_file, notices / 'Python-LICENSE.txt')
            break


def main():
    if os.name != 'nt':
        raise SystemExit('Build this installer on 64-bit Windows, not in WSL.')
    if not PYTHON.is_file():
        run([sys.executable, '-m', 'venv', VENV])
    run([PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check',
         '-r', ROOT / 'requirements.txt', 'pyinstaller==6.21.0'])
    run([PYTHON, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
         '--icon', ROOT / 'program_flow' / 'static' / 'icon.ico',
         '--name', 'ProgramFlow', '--distpath', BUILD / 'release',
         '--workpath', BUILD / 'pyinstaller', '--specpath', BUILD,
         '--add-data', f'{ROOT / "program_flow" / "static"};program_flow/static',
         '--hidden-import', 'pystray._win32',
         '--hidden-import', 'uvicorn.protocols.http.h11_impl',
         '--hidden-import', 'uvicorn.lifespan.on',
         '--hidden-import', 'uvicorn.loops.asyncio',
         '--collect-submodules', 'program_flow',
         ROOT / 'windows_main.py'])
    bundled = BUILD / 'release' / 'ProgramFlow' / 'ProgramFlow.exe'
    if not bundled.is_file():
        raise RuntimeError('PyInstaller did not produce ProgramFlow.exe')
    shutil.copytree(ROOT / 'program_flow', bundled.parent / 'program_flow',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'requirements.txt', 'windows_main.py'):
        shutil.copy2(ROOT / name, bundled.parent / name)
    run([PYTHON, '-c', 'import build_windows; from pathlib import Path; '
         'build_windows.copy_dependency_licenses(Path(r"' + str(bundled.parent) + '"))'])
    iscc = shutil.which('ISCC.exe') or shutil.which('iscc')
    if not iscc:
        raise RuntimeError('Inno Setup compiler (ISCC) is needed on the build machine')
    run([iscc, '/Qp', ROOT / 'installer' / 'program-flow.iss'])
    setup = ROOT / 'release' / 'ProgramFlow-Setup-0.2.6-x64.exe'
    if not setup.is_file():
        raise RuntimeError('Inno Setup did not produce the installer')
    shutil.make_archive(str(ROOT / 'release' / 'ProgramFlow-Portable-0.2.6-x64'),
                        'zip', bundled.parent.parent, bundled.parent.name)
    print('Bundled executable:', bundled)
    print('Windows installer:', setup)


if __name__ == '__main__':
    main()
