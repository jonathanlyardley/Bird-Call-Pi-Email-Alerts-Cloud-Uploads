import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ImportSafetyTests(unittest.TestCase):
    def test_alert_modules_do_not_create_log_dirs_on_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "nested" / "alerts.log"
            code = (
                "import os, sys; "
                f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
                f"os.environ['BIRD_CALL_LOG_PATH'] = {str(log_path)!r}; "
                "import alert_email, alert_poller"
            )

            subprocess.run([sys.executable, "-c", code], check=True)

            self.assertFalse(log_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
