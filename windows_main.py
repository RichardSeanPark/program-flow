"""Bootstrap the editable source beside the executable, never a frozen fallback."""
import importlib.util
from pathlib import Path
import sys


def load_launcher(root=None):
    root = Path(root) if root is not None else (
        Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
        else Path(__file__).resolve().parent)
    package = root / 'program_flow'
    required = ['__init__.py', 'windows_launcher.py', 'app.py', 'kiwoom.py',
                'store.py', 'series.py', 'static/index.html', 'static/app.js']
    if any(not (package / name).is_file() for name in required):
        raise RuntimeError('ProgramFlow.exe 옆의 program_flow 소스 폴더가 없거나 불완전합니다. '
                           '배포 압축을 전부 풀거나 다시 설치해 주세요.')
    # Pin the package path before PyInstaller's importer can select bundled code.
    spec = importlib.util.spec_from_file_location(
        'program_flow', package / '__init__.py', submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules['program_flow'] = module
    spec.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location(
        'program_flow.windows_launcher', package / 'windows_launcher.py')
    launcher = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = launcher
    spec.loader.exec_module(launcher)
    return launcher


def main():
    try:
        return load_launcher().main()
    except Exception as exc:
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'Program Flow', 0x10)
        else:
            raise
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
