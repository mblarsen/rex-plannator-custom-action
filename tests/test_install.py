import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "install.py"
spec = importlib.util.spec_from_file_location("installer", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rex install test ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / "checkout/pi-extension.ts"
        self.source.parent.mkdir()
        self.source.write_text("original companion")
        self.agent = self.root / "pi agent"
        self.target = self.agent / "extensions/rex-plannotator.ts"

    def manage(self, action="install"):
        return installer.manage(action, self.agent, self.source)

    def test_installs_absolute_symlink_with_spaces(self):
        self.manage()
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.readlink(), self.source)
        self.assertEqual(self.target.read_text(), "original companion")

    def test_install_is_idempotent_and_source_updates_are_visible(self):
        self.manage()
        inode = self.target.lstat().st_ino
        self.assertIn("Already installed", self.manage())
        self.assertEqual(self.target.lstat().st_ino, inode)
        self.source.write_text("updated companion")
        self.assertEqual(self.target.read_text(), "updated companion")

    def test_existing_regular_file_is_never_changed(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("user extension")
        for action in ("install", "uninstall"):
            with self.assertRaisesRegex(RuntimeError, "existing file"):
                self.manage(action)
        self.assertEqual(self.target.read_text(), "user extension")

    def test_existing_directory_is_never_changed(self):
        self.target.mkdir(parents=True)
        for action in ("install", "uninstall"):
            with self.assertRaisesRegex(RuntimeError, "existing file or directory"):
                self.manage(action)
        self.assertTrue(self.target.is_dir())

    def test_other_symlink_is_never_changed_even_if_broken(self):
        self.target.parent.mkdir(parents=True)
        other = self.root / "missing-companion.ts"
        self.target.symlink_to(other)
        for action in ("install", "uninstall"):
            with self.assertRaisesRegex(RuntimeError, "another symlink"):
                self.manage(action)
        self.assertEqual(self.target.readlink(), other)

    def test_relative_symlink_to_our_source_is_recognized(self):
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(os.path.relpath(self.source, self.target.parent))
        self.assertIn("Already installed", self.manage())
        self.manage("uninstall")
        self.assertFalse(self.target.is_symlink())

    def test_uninstall_removes_only_our_link(self):
        self.manage()
        other = self.target.with_name("other.ts")
        other.write_text("unrelated extension")
        self.manage("uninstall")
        self.assertFalse(self.target.is_symlink())
        self.assertTrue(self.source.is_file())
        self.assertEqual(other.read_text(), "unrelated extension")
        self.assertTrue(self.target.parent.is_dir())

    def test_uninstall_is_idempotent_and_creates_no_directories(self):
        self.assertIn("Not installed", self.manage("uninstall"))
        self.assertFalse(self.agent.exists())
        self.manage()
        self.manage("uninstall")
        self.assertIn("Not installed", self.manage("uninstall"))

    def test_missing_source_refused_but_its_old_link_can_be_removed(self):
        self.manage()
        self.source.unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.manage()
        self.manage("uninstall")
        self.assertFalse(self.target.is_symlink())

    def test_agent_directory_precedence(self):
        with patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(self.agent)}):
            self.assertEqual(installer.agent_directory(), self.agent)
            self.assertEqual(installer.agent_directory(str(self.root)), self.root)
        with patch.dict(os.environ, {}, clear=True), patch.object(installer.Path, "home", return_value=self.root):
            self.assertEqual(installer.agent_directory(), self.root / ".pi/agent")

    def test_cli_install_and_uninstall_use_custom_agent_directory(self):
        for action in ("install", "uninstall"):
            result = subprocess.run([sys.executable, str(SCRIPT), action, "--agent-dir", str(self.agent)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("/reload", result.stdout)
            self.assertEqual(self.target.is_symlink(), action == "install")

    def test_cli_refusal_returns_failure(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("user extension")
        result = subprocess.run([sys.executable, str(SCRIPT), "--agent-dir", str(self.agent)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Refusing", result.stderr)
        self.assertEqual(self.target.read_text(), "user extension")


if __name__ == "__main__":
    unittest.main()
