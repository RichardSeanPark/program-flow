from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerSourceTests(unittest.TestCase):
    def test_installer_does_not_require_admin_python_or_wsl(self):
        script = (ROOT / 'installer' / 'program-flow.iss').read_text(encoding='utf-8')
        self.assertIn('PrivilegesRequired=lowest', script)
        self.assertIn('MinVersion=10.0', script)
        self.assertIn('{localappdata}', script)
        self.assertIn('ProgramFlow.exe', script)
        self.assertIn('recursesubdirs', script)
        self.assertNotIn('wsl.exe', script.lower())
        self.assertNotIn('C:\\Python', script)

    def test_windows_tz_database_is_included(self):
        dependencies = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        self.assertIn('tzdata==', dependencies)

    def test_windows_main_starts_packaged_launcher(self):
        entry = (ROOT / 'windows_main.py').read_text(encoding='utf-8')
        self.assertIn('spec_from_file_location', entry)
        self.assertIn('Path(sys.executable).resolve().parent', entry)


if __name__ == '__main__':
    unittest.main()
