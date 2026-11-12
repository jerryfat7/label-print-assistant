import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CHECKER = Path(__file__).resolve().parents[1] / "tools/check_public_docs.py"


class PublicDocsTests(unittest.TestCase):
    def test_masked_examples_pass_and_unmasked_values_are_not_echoed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            doc = root / "README.md"
            doc.write_text("张** 138****0000 示例市某路***号\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            result = subprocess.run([sys.executable, str(CHECKER)], cwd=root, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            mobile = "138" + "0" * 8  # Generated fixture, not a contact record.
            doc.write_text(mobile + " 示例路123号\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(CHECKER)], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(mobile.encode(), result.stderr + result.stdout)
            self.assertNotIn("示例路123号".encode(), result.stderr + result.stdout)

    def test_staged_check_reads_index_rather_than_working_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            doc = root / "README.md"
            doc.write_text("138" + "0" * 8, encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            doc.write_text("138****0000", encoding="utf-8")
            result = subprocess.run([sys.executable, str(CHECKER), "--staged"], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
