import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import install


class Install(unittest.TestCase):
    def test_installs_both_clients_and_backs_up_existing_files(self):
        root = Path(tempfile.mkdtemp())
        claude = root / "claude"
        agents = root / "agents"
        command = claude / "commands" / "ds.md"
        command.parent.mkdir(parents=True)
        command.write_text("old command", encoding="utf-8")

        paths = install.install(claude, agents)

        self.assertEqual(len(paths), 3)
        self.assertTrue((claude / "skills" / "ds-director" / "SKILL.md").is_file())
        self.assertTrue((agents / "skills" / "ds-director" / "SKILL.md").is_file())
        self.assertEqual(command.read_text(encoding="utf-8"),
                         (install.ROOT / "skill" / "ds.md").read_text(encoding="utf-8"))
        self.assertEqual(command.with_suffix(".md.bak").read_text(encoding="utf-8"),
                         "old command")

    def test_can_install_only_codex(self):
        root = Path(tempfile.mkdtemp())
        paths = install.install(root / "claude", root / "agents", claude=False)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], root / "agents" / "skills" / "ds-director" / "SKILL.md")
        self.assertFalse((root / "claude").exists())

    def test_python_dash_m_dsd_reaches_the_cli(self):
        result = subprocess.run([sys.executable, "-m", "dsd", "--help"],
                                cwd=install.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dsd tests", result.stdout)


if __name__ == "__main__":
    unittest.main()
