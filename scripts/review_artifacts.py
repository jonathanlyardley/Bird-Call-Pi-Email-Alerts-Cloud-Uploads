#!/usr/bin/env python3
"""Create review artefacts for selected BirdNET-Go detections.

This script is deliberately conservative. It never alters the BirdNET-Go
database or source audio. It copies each selected WAV into /data/review, then
adds filtered listening audio, spectrograms, metadata, and a review-log row.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


DB_PATH = env_path("BIRD_CALL_DB_PATH", "/data/detections/birdnet.db")
AUDIO_ROOT = env_path("BIRD_CALL_AUDIO_DIR", "/data/audio")
REVIEW_ROOT = env_path("BIRD_CALL_REVIEW_DIR", "/data/review")
STATE_PATH = env_path("BIRD_CALL_REVIEW_STATE", "/data/logs/review_artifacts_state.json")
LOG_PATH = env_path("BIRD_CALL_REVIEW_LOG", "/data/logs/review_artifacts.log")

HIGH_CONF_ALL_MIN = 0.95

COMMON_NAMES = {
    "Accipiter gentilis": "Northern Goshawk",
    "Accipiter nisus": "Eurasian Sparrowhawk",
    "Aegithalos caudatus": "Long-tailed Tit",
    "Alauda arvensis": "Eurasian Skylark",
    "Apus apus": "Common Swift",
    "Asio flammeus": "Short-eared Owl",
    "Asio otus": "Long-eared Owl",
    "Athene noctua": "Little Owl",
    "Bubo scandiacus": "Snowy Owl",
    "Buteo buteo": "Common Buzzard",
    "Carduelis carduelis": "European Goldfinch",
    "Chloris chloris": "European Greenfinch",
    "Columba palumbus": "Common Woodpigeon",
    "Corvus frugilegus": "Rook",
    "Corvus monedula": "Eurasian Jackdaw",
    "Cuculus canorus": "Common Cuckoo",
    "Erithacus rubecula": "European Robin",
    "Falco columbarius": "Merlin",
    "Falco peregrinus": "Peregrine Falcon",
    "Falco subbuteo": "Eurasian Hobby",
    "Falco tinnunculus": "Common Kestrel",
    "Haliaeetus albicilla": "White-tailed Eagle",
    "Milvus milvus": "Red Kite",
    "Pandion haliaetus": "Osprey",
    "Pernis apivorus": "European Honey-buzzard",
    "Strix aluco": "Tawny Owl",
    "Turdus merula": "Eurasian Blackbird",
    "Turdus philomelos": "Song Thrush",
    "Tyto alba": "Barn Owl",
}

OWL_SPECIES = {
    "Asio flammeus",
    "Asio otus",
    "Athene noctua",
    "Bubo scandiacus",
    "Strix aluco",
    "Tyto alba",
}

RAPTOR_SPECIES = {
    "Accipiter gentilis",
    "Accipiter nisus",
    "Aquila chrysaetos",
    "Buteo buteo",
    "Circus aeruginosus",
    "Circus cyaneus",
    "Circus pygargus",
    "Falco columbarius",
    "Falco peregrinus",
    "Falco subbuteo",
    "Falco tinnunculus",
    "Haliaeetus albicilla",
    "Milvus milvus",
    "Pandion haliaetus",
    "Pernis apivorus",
}

SWIFT_SPECIES = {"Apus apus"}
FINCH_FOCUS_SPECIES = {"Carduelis carduelis", "Chloris chloris"}
THRUSH_ROBIN_FOCUS_SPECIES = {"Erithacus rubecula", "Turdus merula", "Turdus philomelos"}
CORVID_FOCUS_SPECIES = {"Corvus frugilegus", "Corvus monedula"}


@dataclass(frozen=True)
class Detection:
    detection_id: int
    detected_at: int
    local_time: str
    confidence: float
    scientific_name: str
    clip_name: str


@dataclass(frozen=True)
class ReviewProfile:
    selected: bool
    group: str
    band_low_hz: int
    band_high_hz: int
    common_name: str
    reason: str


@dataclass(frozen=True)
class OutputPaths:
    package_dir: Path
    original: Path
    review_audio: Path
    full_spectrogram: Path
    band_spectrogram: Path
    metadata: Path


def common_name_for(scientific_name: str) -> str:
    return COMMON_NAMES.get(scientific_name, scientific_name)


def slugify(value: str) -> str:
    slug = []
    previous_underscore = False
    for char in value.lower():
        if char.isalnum():
            slug.append(char)
            previous_underscore = False
        elif not previous_underscore:
            slug.append("_")
            previous_underscore = True
    return "".join(slug).strip("_")


def _profile(
    selected: bool,
    scientific_name: str,
    group: str,
    band: tuple[int, int],
    reason: str,
) -> ReviewProfile:
    return ReviewProfile(
        selected=selected,
        group=group,
        band_low_hz=band[0],
        band_high_hz=band[1],
        common_name=common_name_for(scientific_name),
        reason=reason,
    )


def select_review_profile(scientific_name: str, confidence: float) -> ReviewProfile:
    if scientific_name in OWL_SPECIES:
        return _profile(True, scientific_name, "owl", (300, 2000), "owl detections are always reviewed")
    if scientific_name in SWIFT_SPECIES:
        selected = confidence >= 0.90
        reason = "swift focus species" if selected else "below swift focus threshold 0.90"
        return _profile(selected, scientific_name, "swift", (4000, 9000), reason)
    if scientific_name in FINCH_FOCUS_SPECIES:
        selected = confidence >= 0.90
        reason = "finch focus species" if selected else "below finch focus threshold 0.90"
        return _profile(selected, scientific_name, "finch", (2500, 9000), reason)
    if scientific_name in THRUSH_ROBIN_FOCUS_SPECIES:
        selected = confidence >= 0.90
        reason = "thrush/robin focus species" if selected else "below thrush/robin focus threshold 0.90"
        return _profile(selected, scientific_name, "thrush_robin", (2000, 8000), reason)
    if scientific_name in RAPTOR_SPECIES:
        selected = confidence >= 0.90
        reason = "raptor focus species" if selected else "below raptor focus threshold 0.90"
        return _profile(selected, scientific_name, "raptor", (1000, 6000), reason)
    if scientific_name in CORVID_FOCUS_SPECIES:
        selected = confidence >= 0.95
        reason = "high-confidence corvid focus species" if selected else "below corvid focus threshold 0.95"
        return _profile(selected, scientific_name, "corvid", (500, 4000), reason)
    if confidence >= HIGH_CONF_ALL_MIN:
        return _profile(True, scientific_name, "default", (300, 10000), "general high-confidence detection")
    return _profile(False, scientific_name, "default", (300, 10000), "below review threshold")


def build_output_paths(review_root: Path, detection: Detection) -> OutputPaths:
    profile = select_review_profile(detection.scientific_name, detection.confidence)
    species_slug = slugify(detection.scientific_name)
    stem = Path(detection.clip_name).stem
    date_part = detection.local_time.split(" ", 1)[0]
    year, month, _day = date_part.split("-")
    package_dir = review_root / year / month / species_slug / stem
    return OutputPaths(
        package_dir=package_dir,
        original=package_dir / f"{stem}__original.wav",
        review_audio=package_dir / f"{stem}__{profile.group}-review.flac",
        full_spectrogram=package_dir / f"{stem}__spec.png",
        band_spectrogram=package_dir / f"{stem}__{profile.group}-band-spec.png",
        metadata=package_dir / f"{stem}__meta.json",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_metadata(
    detection: Detection,
    profile: ReviewProfile,
    original_wav: Path,
    audio_root: Path,
) -> dict:
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "phase_1_review_artifacts",
        "detection": {
            "id": detection.detection_id,
            "detected_at_unix": detection.detected_at,
            "local_time": detection.local_time,
            "scientific_name": detection.scientific_name,
            "common_name": profile.common_name,
            "confidence": detection.confidence,
            "clip_name": detection.clip_name,
        },
        "review_profile": {
            "selected": profile.selected,
            "group": profile.group,
            "band_hz": [profile.band_low_hz, profile.band_high_hz],
            "reason": profile.reason,
        },
        "evidence": {
            "original_source_path": str(audio_root / detection.clip_name),
            "original_review_copy": str(original_wav),
            "sha256_original_wav": sha256_file(original_wav),
            "evidence_note": "Original WAV is primary evidence. Filtered audio and spectrograms are review aids only.",
        },
        "review": {
            "status": "",
            "reviewer": "",
            "notes": "",
        },
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"last_id": 0}
    try:
        state = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"last_id": 0}
    state.setdefault("last_id", 0)
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def fetch_detections(db_path: Path, last_id: int, since_hours: int, limit: int) -> list[Detection]:
    cutoff = int(time.time() - since_hours * 3600)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.detected_at,
                   datetime(d.detected_at, 'unixepoch', 'localtime') AS local_time,
                   d.confidence, l.scientific_name, d.clip_name
            FROM detections d
            JOIN labels l ON l.id = d.label_id
            WHERE d.id > ?
              AND d.detected_at >= ?
              AND d.clip_name IS NOT NULL
              AND d.clip_name != ''
            ORDER BY d.id ASC
            LIMIT ?
            """,
            (last_id, cutoff, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        Detection(
            detection_id=int(row["id"]),
            detected_at=int(row["detected_at"]),
            local_time=str(row["local_time"]),
            confidence=float(row["confidence"]),
            scientific_name=str(row["scientific_name"]),
            clip_name=str(row["clip_name"]),
        )
        for row in rows
    ]


def run_command(command: list[str], logger: logging.Logger) -> None:
    logger.info("running: %s", " ".join(command))
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def create_review_audio(source: Path, destination: Path, profile: ReviewProfile, logger: logging.Logger) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-af",
        f"highpass=f={profile.band_low_hz},lowpass=f={profile.band_high_hz}",
        "-c:a",
        "flac",
        str(destination),
    ]
    run_command(command, logger)


def create_spectrograms(source: Path, paths: OutputPaths, profile: ReviewProfile, logger: logging.Logger) -> None:
    full_command, band_command = build_spectrogram_commands(source, paths, profile)
    run_command(full_command, logger)
    run_command(band_command, logger)


def build_spectrogram_commands(source: Path, paths: OutputPaths, profile: ReviewProfile) -> tuple[list[str], list[str]]:
    full_command = [
        "sox",
        str(source),
        "-n",
        "spectrogram",
        "-x",
        "1200",
        "-Y",
        "700",
        "-z",
        "90",
        "-t",
        f"{profile.common_name} {profile.group} review",
        "-o",
        str(paths.full_spectrogram),
    ]
    band_command = [
        "sox",
        str(source),
        "-n",
        "sinc",
        f"{profile.band_low_hz}-{profile.band_high_hz}",
        "spectrogram",
        "-x",
        "1200",
        "-Y",
        "700",
        "-z",
        "90",
        "-t",
        f"{profile.common_name} {profile.band_low_hz}-{profile.band_high_hz} Hz",
        "-o",
        str(paths.band_spectrogram),
    ]
    return full_command, band_command


def existing_review_ids(review_log: Path) -> set[int]:
    if not review_log.exists():
        return set()
    with review_log.open(newline="") as handle:
        return {int(row["detection_id"]) for row in csv.DictReader(handle) if row.get("detection_id")}


def append_review_log(review_root: Path, detection: Detection, profile: ReviewProfile, paths: OutputPaths) -> None:
    review_log = review_root / "review-log.csv"
    seen = existing_review_ids(review_log)
    if detection.detection_id in seen:
        return
    review_log.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "detection_id",
        "local_time",
        "scientific_name",
        "common_name",
        "confidence",
        "group",
        "band_low_hz",
        "band_high_hz",
        "package_dir",
        "original_wav",
        "review_audio",
        "full_spectrogram",
        "band_spectrogram",
        "metadata",
        "review_status",
        "reviewer",
        "review_notes",
    ]
    write_header = not review_log.exists()
    with review_log.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "detection_id": detection.detection_id,
                "local_time": detection.local_time,
                "scientific_name": detection.scientific_name,
                "common_name": profile.common_name,
                "confidence": f"{detection.confidence:.2f}",
                "group": profile.group,
                "band_low_hz": profile.band_low_hz,
                "band_high_hz": profile.band_high_hz,
                "package_dir": paths.package_dir,
                "original_wav": paths.original,
                "review_audio": paths.review_audio,
                "full_spectrogram": paths.full_spectrogram,
                "band_spectrogram": paths.band_spectrogram,
                "metadata": paths.metadata,
                "review_status": "",
                "reviewer": "",
                "review_notes": "",
            }
        )


def create_daily_index(review_root: Path, date_text: str) -> Path:
    index_dir = review_root / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / f"{date_text}.html"
    metas = sorted(review_root.glob(f"{date_text[:4]}/{date_text[5:7]}/*/*/*__meta.json"))
    rows = []
    for meta_path in metas:
        data = json.loads(meta_path.read_text())
        det = data["detection"]
        profile = data["review_profile"]
        package_dir = meta_path.parent
        files = {p.name: p for p in package_dir.iterdir() if p.is_file()}
        review_audio = next((p for name, p in files.items() if name.endswith("-review.flac")), None)
        full_spec = next((p for name, p in files.items() if name.endswith("__spec.png")), None)
        band_spec = next((p for name, p in files.items() if name.endswith("-band-spec.png")), None)
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(det['id']))}</td>"
            f"<td>{html.escape(det['local_time'])}</td>"
            f"<td>{html.escape(det['common_name'])}</td>"
            f"<td>{html.escape(det['scientific_name'])}</td>"
            f"<td>{float(det['confidence']):.2f}</td>"
            f"<td>{html.escape(profile['group'])}</td>"
            f"<td>{_link(review_audio, 'review audio')}</td>"
            f"<td>{_link(full_spec, 'full spec')}</td>"
            f"<td>{_link(band_spec, 'band spec')}</td>"
            f"<td>{_link(meta_path, 'metadata')}</td>"
            "</tr>"
        )
    html_text = (
        "<!doctype html><meta charset=\"utf-8\">"
        f"<title>Bird call review {html.escape(date_text)}</title>"
        "<style>body{font-family:sans-serif;max-width:1200px;margin:2rem auto;}"
        "table{border-collapse:collapse;width:100%;}td,th{border:1px solid #ccc;padding:.35rem;text-align:left;}"
        "th{background:#eee;}</style>"
        f"<h1>Bird call review {html.escape(date_text)}</h1>"
        "<p>Filtered audio and spectrograms are review aids. Original WAV remains the evidence source.</p>"
        "<table><thead><tr><th>ID</th><th>Time</th><th>Common</th><th>Scientific</th><th>Conf</th>"
        "<th>Group</th><th>Audio</th><th>Full</th><th>Band</th><th>Meta</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )
    index_path.write_text(html_text)
    return index_path


def _link(path: Path | None, label: str) -> str:
    if path is None:
        return ""
    return f'<a href="file://{html.escape(str(path))}">{html.escape(label)}</a>'


def process_detection(
    detection: Detection,
    audio_root: Path,
    review_root: Path,
    force: bool,
    dry_run: bool,
    logger: logging.Logger,
) -> bool:
    profile = select_review_profile(detection.scientific_name, detection.confidence)
    if not profile.selected:
        logger.info("skip id=%s species=%s reason=%s", detection.detection_id, detection.scientific_name, profile.reason)
        return False

    source = audio_root / detection.clip_name
    if not source.exists():
        logger.warning("source missing id=%s path=%s", detection.detection_id, source)
        return False

    paths = build_output_paths(review_root, detection)
    if paths.metadata.exists() and not force:
        logger.info("already processed id=%s package=%s", detection.detection_id, paths.package_dir)
        return False

    logger.info(
        "process id=%s species=%s conf=%.2f group=%s band=%s-%s",
        detection.detection_id,
        detection.scientific_name,
        detection.confidence,
        profile.group,
        profile.band_low_hz,
        profile.band_high_hz,
    )
    if dry_run:
        return True

    paths.package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, paths.original)
    create_review_audio(paths.original, paths.review_audio, profile, logger)
    create_spectrograms(paths.original, paths, profile, logger)
    metadata = build_metadata(detection, profile, paths.original, audio_root)
    metadata["outputs"] = {
        "package_dir": str(paths.package_dir),
        "review_audio": str(paths.review_audio),
        "full_spectrogram": str(paths.full_spectrogram),
        "band_spectrogram": str(paths.band_spectrogram),
        "metadata": str(paths.metadata),
    }
    paths.metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True))
    append_review_log(review_root, detection, profile, paths)
    create_daily_index(review_root, detection.local_time.split(" ", 1)[0])
    return True


def configure_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s review_artifacts: %(message)s",
    )
    return logging.getLogger("review_artifacts")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create BirdNET-Go review artefacts")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--audio-root", type=Path, default=AUDIO_ROOT)
    parser.add_argument("--review-root", type=Path, default=REVIEW_ROOT)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--since-hours", type=int, default=48)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logger = configure_logging(args.log)
    state = load_state(args.state)
    last_id = int(state.get("last_id", 0))
    detections = fetch_detections(args.db, last_id, args.since_hours, args.limit)
    processed = 0
    scanned = 0
    max_id = last_id
    for detection in detections:
        scanned += 1
        max_id = max(max_id, detection.detection_id)
        try:
            if process_detection(detection, args.audio_root, args.review_root, args.force, args.dry_run, logger):
                processed += 1
        except subprocess.CalledProcessError as exc:
            logger.error(
                "command failed id=%s returncode=%s stderr=%s",
                detection.detection_id,
                exc.returncode,
                (exc.stderr or "")[:600],
            )
        except Exception:
            logger.exception("processing failed id=%s", detection.detection_id)
    if not args.dry_run:
        state["last_id"] = max_id
        state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        save_state(args.state, state)
    logger.info("run complete scanned=%d processed=%d last_id=%d", scanned, processed, max_id)
    print(f"scanned={scanned} processed={processed} last_id={max_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
