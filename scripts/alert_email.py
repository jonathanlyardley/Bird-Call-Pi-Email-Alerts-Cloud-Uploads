#!/usr/bin/env python3
"""Species-filtered email alert with audio-clip attachment.

Invoked by BirdNET-Go's `script` notification provider on every detection event.
Reads detection metadata from stdin JSON and/or environment variables, checks
whether the species is in the priority list, and (if so) sends an email with
the audio clip attached via Gmail SMTP.

Secrets live in an env file outside Git, loaded at runtime so BirdNET-Go config
does not contain the SMTP app password.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


LOG_PATH = env_path("BIRD_CALL_LOG_PATH", "/data/logs/alerts.log")
SECRETS_PATH = env_path("BIRD_CALL_EMAIL_ENV", "/opt/bird-call-alerts/secrets/email.env")
DEFAULT_CLIPS_ROOT = env_path("BIRD_CALL_AUDIO_DIR", "/data/audio")
REVIEW_ROOT = env_path("BIRD_CALL_REVIEW_DIR", "/data/review")
DEFAULT_STATION_LABEL = os.environ.get("BIRD_CALL_STATION_LABEL", "Bird monitoring station")

if os.name == "nt":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
else:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
log = logging.getLogger("alert_email")


def load_secrets(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file. Comments and blank lines ignored."""
    if not path.exists():
        raise FileNotFoundError(f"secrets file missing: {path}")
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    required = {"SMTP_USER", "SMTP_PASS", "TO_ADDRESSES", "PRIORITY_SPECIES"}
    missing = required - set(out)
    if missing:
        raise ValueError(f"missing keys in {path}: {missing}")
    return out


def read_event() -> dict:
    """Pull metadata from stdin JSON and fall back to env vars."""
    data: dict = {}
    stdin_bytes = sys.stdin.read() if not sys.stdin.isatty() else ""
    if stdin_bytes.strip():
        try:
            parsed = json.loads(stdin_bytes)
            # Flatten any nested dicts (e.g. metadata: {...}) into the top level.
            if isinstance(parsed, dict):
                data.update(parsed)
                for k, v in list(parsed.items()):
                    if isinstance(v, dict):
                        for k2, v2 in v.items():
                            data.setdefault(k2, v2)
        except json.JSONDecodeError:
            log.warning("stdin not valid JSON, using env vars only")
    for key, value in os.environ.items():
        if key.startswith(("NOTIFICATION_", "BIRDNET_", "DETECTION_", "METADATA_", "BN_")):
            data.setdefault(key, value)
    # Log the raw event keys to help diagnose field-name drift.
    log.info("raw event keys=%s", sorted(data.keys()))
    log.info("raw event (truncated) =%s", json.dumps(data, default=str)[:1000])
    return data


def pick(data: dict, *candidates: str, default: str = "") -> str:
    """Return the first non-empty value under any of the candidate keys (any case)."""
    lowered = {k.lower(): v for k, v in data.items() if isinstance(v, (str, int, float))}
    for cand in candidates:
        v = lowered.get(cand.lower())
        if v not in (None, ""):
            return str(v)
    return default


def find_clip(clip_name: str, search_root: Path = DEFAULT_CLIPS_ROOT) -> Path | None:
    if not clip_name:
        return None
    direct = search_root / clip_name
    if direct.exists():
        return direct
    for match in search_root.rglob(Path(clip_name).name):
        return match
    return None


def find_existing_path(path_text: str) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text)
    return path if path.exists() else None


def find_review_audio_for_clip(clip_name: str, review_root: Path = REVIEW_ROOT) -> Path | None:
    if not clip_name or not review_root.exists():
        return None
    stem = Path(clip_name).stem
    matches = sorted(review_root.rglob(f"{stem}__*-review.flac"))
    return matches[0] if matches else None


def audio_subtype(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".flac":
        return "flac"
    if suffix == ".wav":
        return "wav"
    return "octet-stream"


def build_email_message(
    secrets: dict[str, str],
    subject: str,
    body: str,
    attachments: list[Path | None],
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = secrets["SMTP_USER"]
    msg["To"] = secrets["TO_ADDRESSES"]
    msg["Subject"] = subject
    msg.set_content(body)

    for attachment in attachments:
        if attachment is None or not attachment.exists():
            continue
        size_mb = attachment.stat().st_size / 1_048_576
        if size_mb > 20:
            log.warning("clip %s is %.1f MB - Gmail limit is 25 MB, skipping attachment",
                        attachment, size_mb)
            continue
        msg.add_attachment(
            attachment.read_bytes(),
            maintype="audio",
            subtype=audio_subtype(attachment),
            filename=attachment.name,
        )
    return msg


def compose_body(
    common: str,
    scientific: str,
    confidence: str,
    detected_at: str,
    clip_name: str,
    clip_path: Path | None,
    review_audio_path: Path | None,
    station_label: str = DEFAULT_STATION_LABEL,
) -> str:
    original_status = "attached as primary evidence" if clip_path else "original clip not found on disk"
    review_status = (
        "attached as filtered listening aid only; not isolated and not source-separated"
        if review_audio_path
        else "not available"
    )
    return (
        f"Priority species detected at {station_label}.\n\n"
        f"Species     : {common}\n"
        f"Scientific  : {scientific}\n"
        f"Confidence  : {confidence}\n"
        f"Detected at : {detected_at}\n"
        f"Clip file   : {clip_name or '(none)'}\n\n"
        f"Attachments:\n"
        f"- Original WAV: {original_status}.\n"
        f"- Filtered review FLAC: {review_status}.\n\n"
        f"Important: the filtered review clip is a listening aid for the target frequency band. "
        f"It is not isolated target-species audio and not source-separated evidence. "
        f"The original WAV remains the evidence source.\n"
    )


def send_email(secrets: dict[str, str], subject: str, body: str, attachments: list[Path | None]) -> None:
    """Send via Gmail SMTP with retry on transient network errors.

    Gmail/DNS occasionally hiccups; without a retry, a 1-second DNS failure
    loses the entire alert. Three attempts with exponential backoff fixes it.
    """
    import time

    msg = build_email_message(secrets, subject, body, attachments)

    last_exc: Exception | None = None
    for attempt in (1, 2, 3):
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(secrets["SMTP_USER"], secrets["SMTP_PASS"])
                smtp.send_message(msg)
            if attempt > 1:
                log.info("send_email succeeded on attempt %s", attempt)
            return
        except (OSError, smtplib.SMTPException) as exc:
            last_exc = exc
            log.warning("send_email attempt %s/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)  # 5s, 10s
    # All retries failed
    raise last_exc if last_exc else RuntimeError("send_email failed without exception")


def main() -> int:
    try:
        secrets = load_secrets(SECRETS_PATH)
    except Exception:
        log.exception("failed to load secrets")
        return 2

    priority = [s.strip().lower() for s in secrets["PRIORITY_SPECIES"].split(",") if s.strip()]
    if not priority:
        log.error("PRIORITY_SPECIES is empty - no alerts will fire")
        return 0

    event = read_event()
    common = pick(
        event,
        "common_name", "commonName", "CommonName",
        "species", "Species", "species_name", "SpeciesName",
        "SpeciesCommonName", "speciesCommonName",
        "title", "Title",       # BirdNET-Go may pack species into the title field
    )
    scientific = pick(
        event,
        "scientific_name", "scientificName", "ScientificName",
        "sciName", "SciName", "latinName", "LatinName",
    )
    confidence = pick(
        event,
        "confidence", "Confidence",
        "confidence_percent", "ConfidencePercent",
        default="?",
    )
    clip_name = pick(
        event,
        "clip_name", "clipName", "ClipName",
        "audio_file", "AudioFile", "audioFile",
    )
    review_audio_name = pick(
        event,
        "review_audio", "review_audio_path", "reviewClip", "review_clip",
        "filtered_audio", "filtered_clip",
    )
    detected_at = pick(
        event,
        "detected_at", "detectedAt", "DetectionTime",
        "timestamp", "Timestamp",
    )

    log.info(
        "event species=%r scientific=%r confidence=%s clip=%r",
        common, scientific, confidence, clip_name,
    )

    if not common:
        log.info("no species in event - skipping")
        return 0

    # Substring match (case-insensitive) so "Tawny Owl" matches "Tawny Owl"
    # and "Blackbird" matches "Eurasian Blackbird" - BirdNET names vary.
    common_lc = common.lower()
    matched = next((p for p in priority if p in common_lc or common_lc in p), None)
    if matched is None:
        log.info("not a priority species: %s", common)
        return 0
    log.info("priority match: %s matched rule %r", common, matched)

    clip_path = find_clip(clip_name)
    review_audio_path = find_existing_path(review_audio_name) or find_review_audio_for_clip(clip_name)
    station_label = secrets.get("STATION_LABEL", DEFAULT_STATION_LABEL)
    subject = f"{common} detected at {station_label}"
    body = compose_body(
        common=common,
        scientific=scientific,
        confidence=confidence,
        detected_at=detected_at,
        clip_name=clip_name,
        clip_path=clip_path,
        review_audio_path=review_audio_path,
        station_label=station_label,
    )

    try:
        send_email(secrets, subject, body, [clip_path, review_audio_path])
        log.info("email sent for %s (clip=%s review_audio=%s)", common, clip_path, review_audio_path)
    except Exception:
        log.exception("send_email failed")
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
