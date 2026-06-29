import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_artifacts


class ReviewArtifactTests(unittest.TestCase):
    def test_swift_high_confidence_is_selected_with_swift_band(self):
        decision = review_artifacts.select_review_profile("Apus apus", 0.93)

        self.assertTrue(decision.selected)
        self.assertEqual(decision.group, "swift")
        self.assertEqual(decision.band_low_hz, 4000)
        self.assertEqual(decision.band_high_hz, 9000)

    def test_robin_below_focus_threshold_is_not_selected(self):
        decision = review_artifacts.select_review_profile("Erithacus rubecula", 0.80)

        self.assertFalse(decision.selected)
        self.assertIn("below", decision.reason)

    def test_owl_is_selected_even_below_priority_email_threshold(self):
        decision = review_artifacts.select_review_profile("Strix aluco", 0.61)

        self.assertTrue(decision.selected)
        self.assertEqual(decision.group, "owl")
        self.assertEqual((decision.band_low_hz, decision.band_high_hz), (300, 2000))

    def test_output_paths_are_date_species_and_detection_scoped(self):
        detection = review_artifacts.Detection(
            detection_id=22351,
            detected_at=1780174112,
            local_time="2026-05-30 21:48:32",
            confidence=0.99,
            scientific_name="Apus apus",
            clip_name="2026/05/apus_apus_99p_20260530T214834Z.wav",
        )

        paths = review_artifacts.build_output_paths(Path("/data/review"), detection)

        self.assertEqual(paths.package_dir, Path("/data/review/2026/05/apus_apus/apus_apus_99p_20260530T214834Z"))
        self.assertEqual(paths.original.name, "apus_apus_99p_20260530T214834Z__original.wav")
        self.assertEqual(paths.review_audio.name, "apus_apus_99p_20260530T214834Z__swift-review.flac")
        self.assertEqual(paths.metadata.name, "apus_apus_99p_20260530T214834Z__meta.json")

    def test_metadata_records_original_hash_and_review_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "clip.wav"
            wav.write_bytes(b"review-test-audio")
            detection = review_artifacts.Detection(
                detection_id=1,
                detected_at=1780174112,
                local_time="2026-05-30 21:48:32",
                confidence=0.99,
                scientific_name="Apus apus",
                clip_name="2026/05/apus_apus_99p_20260530T214834Z.wav",
            )
            profile = review_artifacts.select_review_profile(detection.scientific_name, detection.confidence)

            metadata = review_artifacts.build_metadata(detection, profile, wav, Path("/data/audio"))

        self.assertEqual(metadata["detection"]["id"], 1)
        self.assertEqual(metadata["detection"]["scientific_name"], "Apus apus")
        self.assertEqual(metadata["review_profile"]["group"], "swift")
        self.assertEqual(metadata["review_profile"]["band_hz"], [4000, 9000])
        self.assertEqual(
            metadata["evidence"]["sha256_original_wav"],
            "5137f8a35fa867e560c227d550055c3c738507cf5823f01df119e3e105c73320",
        )

    def test_spectrogram_commands_use_total_height_option_supported_by_pi_sox(self):
        profile = review_artifacts.select_review_profile("Apus apus", 0.99)
        detection = review_artifacts.Detection(
            detection_id=22351,
            detected_at=1780174112,
            local_time="2026-05-30 21:48:32",
            confidence=0.99,
            scientific_name="Apus apus",
            clip_name="2026/05/apus_apus_99p_20260530T214834Z.wav",
        )
        paths = review_artifacts.build_output_paths(Path("/data/review"), detection)

        full_command, band_command = review_artifacts.build_spectrogram_commands(
            Path("/tmp/original.wav"),
            paths,
            profile,
        )

        self.assertIn("-Y", full_command)
        self.assertNotIn("-y", full_command)
        self.assertIn("sinc", band_command)
        self.assertIn("4000-9000", band_command)


if __name__ == "__main__":
    unittest.main()
