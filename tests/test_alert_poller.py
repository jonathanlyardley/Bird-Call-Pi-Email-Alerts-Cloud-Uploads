import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import alert_poller


class AlertPollerTests(unittest.TestCase):
    def test_build_alert_event_includes_detection_id_and_review_audio_path(self):
        row = {
            "id": 22351,
            "detected_at": 1780174112,
            "confidence": 0.99,
            "clip_name": "2026/05/apus_apus_99p_20260530T214834Z.wav",
            "scientific_name": "Apus apus",
        }

        event = alert_poller.build_alert_event(
            row,
            common="Common Swift",
            review_audio_path=Path("/data/review/2026/05/apus_apus/example__swift-review.flac"),
        )

        self.assertEqual(event["detection_id"], "22351")
        self.assertEqual(event["common_name"], "Common Swift")
        self.assertEqual(event["scientific_name"], "Apus apus")
        self.assertEqual(event["confidence"], "0.99")
        self.assertEqual(event["review_audio_path"], "/data/review/2026/05/apus_apus/example__swift-review.flac")

    def test_failed_alert_does_not_advance_last_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._make_polling_fixture(Path(tmp))

            with self._patched_paths(paths), \
                    mock.patch.object(alert_poller, "ensure_review_audio", return_value=None), \
                    mock.patch.object(alert_poller, "fire_alert", return_value=False):
                result = alert_poller.main()

            state = json.loads(paths["state"].read_text())

        self.assertEqual(result, 0)
        self.assertEqual(state["last_id"], 0)

    def test_successful_alert_advances_last_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._make_polling_fixture(Path(tmp))

            with self._patched_paths(paths), \
                    mock.patch.object(alert_poller, "ensure_review_audio", return_value=None), \
                    mock.patch.object(alert_poller, "fire_alert", return_value=True):
                result = alert_poller.main()

            state = json.loads(paths["state"].read_text())

        self.assertEqual(result, 0)
        self.assertEqual(state["last_id"], 1)
        self.assertIn("Common Swift", state["cooldowns"])

    def _make_polling_fixture(self, root: Path) -> dict[str, Path]:
        db_path = root / "birdnet.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE labels (id INTEGER PRIMARY KEY, scientific_name TEXT NOT NULL)")
        conn.execute(
            """
            CREATE TABLE detections (
                id INTEGER PRIMARY KEY,
                detected_at INTEGER NOT NULL,
                confidence REAL NOT NULL,
                clip_name TEXT,
                label_id INTEGER NOT NULL
            )
            """
        )
        conn.execute("INSERT INTO labels (id, scientific_name) VALUES (1, 'Apus apus')")
        conn.execute(
            """
            INSERT INTO detections (id, detected_at, confidence, clip_name, label_id)
            VALUES (1, 1780174112, 0.99, '2026/05/apus_apus_99p_20260530T214834Z.wav', 1)
            """
        )
        conn.commit()
        conn.close()

        secrets_path = root / "email.env"
        secrets_path.write_text("PRIORITY_SPECIES=Common Swift\n")
        state_path = root / "alert_state.json"

        return {"db": db_path, "secrets": secrets_path, "state": state_path}

    def _patched_paths(self, paths: dict[str, Path]):
        return mock.patch.multiple(
            alert_poller,
            DB_PATH=paths["db"],
            SECRETS_PATH=paths["secrets"],
            STATE_PATH=paths["state"],
        )


if __name__ == "__main__":
    unittest.main()
