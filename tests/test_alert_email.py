import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import alert_email


class AlertEmailTests(unittest.TestCase):
    def test_build_email_message_attaches_original_and_review_aid(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "apus_apus_99p.wav"
            review = Path(tmp) / "apus_apus_99p__swift-review.flac"
            original.write_bytes(b"RIFF fake wav")
            review.write_bytes(b"fLaC fake flac")

            msg = alert_email.build_email_message(
                {"SMTP_USER": "from@example.com", "TO_ADDRESSES": "to@example.com"},
                "Common Swift detected",
                "Original clip is primary evidence.\nFiltered review clip is a listening aid only.",
                [original, review],
            )

        attachments = list(msg.iter_attachments())
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].get_filename(), "apus_apus_99p.wav")
        self.assertEqual(attachments[0].get_content_subtype(), "wav")
        self.assertEqual(attachments[1].get_filename(), "apus_apus_99p__swift-review.flac")
        self.assertEqual(attachments[1].get_content_subtype(), "flac")

    def test_compose_body_explains_filtered_clip_is_not_isolation(self):
        body = alert_email.compose_body(
            common="Common Swift",
            scientific="Apus apus",
            confidence="0.99",
            detected_at="2026-05-30 21:48:32 BST",
            clip_name="2026/05/apus_apus_99p_20260530T214834Z.wav",
            clip_path=Path("/data/audio/2026/05/apus_apus_99p_20260530T214834Z.wav"),
            review_audio_path=Path("/data/review/2026/05/apus_apus/example__swift-review.flac"),
        )

        self.assertIn("Original WAV", body)
        self.assertIn("primary evidence", body)
        self.assertIn("Filtered review", body)
        self.assertIn("not isolated", body)
        self.assertIn("not source-separated", body)
        self.assertNotIn("Salis" + "bury", body)

    def test_compose_body_uses_configurable_station_label(self):
        body = alert_email.compose_body(
            common="Tawny Owl",
            scientific="Strix aluco",
            confidence="0.98",
            detected_at="2026-05-30 23:14:00 BST",
            clip_name="strix_aluco.wav",
            clip_path=None,
            review_audio_path=None,
            station_label="Garden recorder",
        )

        self.assertIn("Garden recorder", body)
        self.assertNotIn("St " + "Pamd" + "y", body)

    def test_find_review_audio_for_clip_falls_back_to_review_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "2026" / "05" / "apus_apus" / "apus_apus_99p_20260530T214834Z"
            review.mkdir(parents=True)
            review_audio = review / "apus_apus_99p_20260530T214834Z__swift-review.flac"
            review_audio.write_bytes(b"flac")

            found = alert_email.find_review_audio_for_clip(
                "2026/05/apus_apus_99p_20260530T214834Z.wav",
                review_root=root,
            )

        self.assertEqual(found, review_audio)


if __name__ == "__main__":
    unittest.main()
