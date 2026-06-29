#!/usr/bin/env python3
"""Poll the BirdNET-Go SQLite DB for new priority-species detections and fire
email alerts.

Runs every minute via a systemd timer. Bypasses BirdNET-Go's internal
notification dispatcher - which in our nightly doesn't forward regular
(non-new-species) detections to push providers. Instead we:

1. Load priority species list + cooldown from the shared secrets file.
2. Read state (last processed detection id + per-species last-alert timestamp).
3. SELECT new detections (id > last_id, confidence >= threshold).
4. For each hit, match species (substring, case-insensitive). If in priority
   list AND cooldown has elapsed, shell out to alert_email.py with the event
   JSON on stdin.
5. Persist state.

Atomic enough for minute-granularity; races are tolerated because cooldown
prevents dup emails.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


DB_PATH = env_path("BIRD_CALL_DB_PATH", "/data/detections/birdnet.db")
SECRETS_PATH = env_path("BIRD_CALL_EMAIL_ENV", "/opt/bird-call-alerts/secrets/email.env")
STATE_PATH = env_path("BIRD_CALL_ALERT_STATE", "/data/logs/alert_poller_state.json")
LOG_PATH = env_path("BIRD_CALL_LOG_PATH", "/data/logs/alerts.log")
ALERT_SCRIPT = env_path(
    "BIRD_CALL_ALERT_SCRIPT",
    str(Path(__file__).resolve().with_name("alert_email.py")),
)

CONFIDENCE_MIN = 0.95          # bird email alerts only fire at 95% confidence or higher
COOLDOWN_MINUTES = 5           # per-species

if os.name == "nt":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s poller: %(message)s")
else:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s poller: %(message)s",
    )
log = logging.getLogger("alert_poller")


def load_priority(path: Path) -> list[str]:
    if not path.exists():
        return []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("PRIORITY_SPECIES="):
            raw = line.split("=", 1)[1].strip().strip('"').strip("'")
            return [s.strip().lower() for s in raw.split(",") if s.strip()]
    return []


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"last_id": 0, "cooldowns": {}}
    try:
        data = json.loads(STATE_PATH.read_text())
        data.setdefault("last_id", 0)
        data.setdefault("cooldowns", {})
        return data
    except json.JSONDecodeError:
        log.warning("state file unreadable, resetting")
        return {"last_id": 0, "cooldowns": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_PATH)


def species_matches(common: str, priority: list[str]) -> str | None:
    """Case-insensitive substring match against any priority entry."""
    common_lc = common.lower()
    for rule in priority:
        if rule in common_lc or common_lc in rule:
            return rule
    return None


def fire_alert(event: dict) -> bool:
    """Shell out to alert_email.py, piping event JSON on stdin."""
    try:
        proc = subprocess.run(
            [sys.executable, str(ALERT_SCRIPT)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            timeout=90,
        )
        if proc.returncode != 0:
            log.error(
                "alert_email.py exit=%s stderr=%s",
                proc.returncode, proc.stderr.strip()[:400],
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        log.error("alert_email.py timed out after 90s")
        return False
    except Exception:
        log.exception("alert_email.py invocation failed")
        return False


def build_alert_event(row, common: str, review_audio_path: Path | None = None) -> dict:
    event = {
        "detection_id": str(row["id"]),
        "common_name": common,
        "scientific_name": row["scientific_name"],
        "confidence": f"{row['confidence']:.2f}",
        "clip_name": row["clip_name"] or "",
        "detected_at": datetime.fromtimestamp(
            row["detected_at"], tz=timezone.utc
        ).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    if review_audio_path is not None:
        event["review_audio_path"] = str(review_audio_path).replace("\\", "/")
    return event


def ensure_review_audio(row) -> Path | None:
    """Create/find Phase 1 review artefacts before emailing, if possible."""
    try:
        import review_artifacts

        detection = review_artifacts.Detection(
            detection_id=int(row["id"]),
            detected_at=int(row["detected_at"]),
            local_time=row["local_time"],
            confidence=float(row["confidence"]),
            scientific_name=row["scientific_name"],
            clip_name=row["clip_name"] or "",
        )
        paths = review_artifacts.build_output_paths(review_artifacts.REVIEW_ROOT, detection)
        if not paths.review_audio.exists():
            review_artifacts.process_detection(
                detection=detection,
                audio_root=review_artifacts.AUDIO_ROOT,
                review_root=review_artifacts.REVIEW_ROOT,
                force=False,
                dry_run=False,
                logger=log,
            )
        return paths.review_audio if paths.review_audio.exists() else None
    except Exception:
        log.exception("could not create review artefact for detection id=%s", row["id"])
        return None


def main() -> int:
    priority = load_priority(SECRETS_PATH)
    if not priority:
        log.error("no priority species loaded from %s - aborting", SECRETS_PATH)
        return 1

    if not DB_PATH.exists():
        log.info("DB not yet present (%s) - nothing to do", DB_PATH)
        return 0

    state = load_state()
    last_id = state["last_id"]
    cooldowns: dict[str, float] = state["cooldowns"]
    now_ts = time.time()
    cooldown_secs = COOLDOWN_MINUTES * 60

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT d.id, d.detected_at, d.confidence, d.clip_name,
                   l.scientific_name,
                   datetime(d.detected_at, 'unixepoch', 'localtime') AS local_time
            FROM detections d
            JOIN labels l ON l.id = d.label_id
            WHERE d.id > ?
              AND d.confidence >= ?
            ORDER BY d.id ASC
            """,
            (last_id, CONFIDENCE_MIN),
        ).fetchall()
    finally:
        conn.close()

    alerts_sent = 0
    processed_last_id = last_id
    for row in rows:
        row_id = int(row["id"])

        # We only have scientific_name in the DB. Use it as the species string;
        # priority list contains common names - substring match still works if
        # any priority entry is contained in the scientific OR vice versa.
        # For accuracy, also derive common name from scientific via hard-coded
        # map of UK priority species.
        sci = row["scientific_name"]
        common = SCI_TO_COMMON.get(sci, sci)

        matched = species_matches(common, priority)
        if matched is None:
            # Also try against scientific name directly
            matched = species_matches(sci, priority)

        if matched is None:
            processed_last_id = max(processed_last_id, row_id)
            continue

        # Cooldown
        last_alert = cooldowns.get(common, 0.0)
        if now_ts - last_alert < cooldown_secs:
            log.info(
                "cooldown active for %s (%.0fs since last) - skipping",
                common, now_ts - last_alert,
            )
            processed_last_id = max(processed_last_id, row_id)
            continue

        review_audio_path = ensure_review_audio(row)
        event = build_alert_event(row, common, review_audio_path)
        log.info("firing alert for %s (conf %.2f, id %s)",
                 common, row["confidence"], row["id"])

        if fire_alert(event):
            cooldowns[common] = now_ts
            alerts_sent += 1
            processed_last_id = max(processed_last_id, row_id)
        else:
            log.error(
                "alert failed for id %s; leaving last_id=%s so the next timer run can retry",
                row_id,
                processed_last_id,
            )
            break

    state["last_id"] = processed_last_id
    state["cooldowns"] = cooldowns
    save_state(state)

    if rows:
        log.info("poll complete: scanned=%d sent=%d last_id=%d",
                 len(rows), alerts_sent, processed_last_id)

    return 0


# Scientific-to-UK-common-name map for priority species.
# BirdNET-Go's DB only stores scientific names; common names are resolved via
# the locale file at runtime but not persisted. This map lets our substring
# match work against the priority list (which uses common names).
SCI_TO_COMMON: dict[str, str] = {
    # Owls
    "Strix aluco": "Tawny Owl",
    "Tyto alba": "Barn Owl",
    "Athene noctua": "Little Owl",
    "Asio otus": "Long-eared Owl",
    "Asio flammeus": "Short-eared Owl",
    "Bubo scandiacus": "Snowy Owl",
    # Raptors
    "Milvus milvus": "Red Kite",
    "Buteo buteo": "Common Buzzard",
    "Accipiter nisus": "Eurasian Sparrowhawk",
    "Accipiter gentilis": "Northern Goshawk",
    "Circus aeruginosus": "Western Marsh-Harrier",
    "Circus cyaneus": "Hen Harrier",
    "Circus pygargus": "Montagu's Harrier",
    "Aquila chrysaetos": "Golden Eagle",
    "Haliaeetus albicilla": "White-tailed Eagle",
    "Pandion haliaetus": "Osprey",
    "Falco subbuteo": "Eurasian Hobby",
    "Falco peregrinus": "Peregrine Falcon",
    "Falco tinnunculus": "Common Kestrel",
    "Falco columbarius": "Merlin",
    "Pernis apivorus": "European Honey-buzzard",
    # Red List selection (UK BoCC5 - major species)
    "Cuculus canorus": "Common Cuckoo",
    "Apus apus": "Common Swift",
    "Caprimulgus europaeus": "European Nightjar",
    "Streptopelia turtur": "European Turtle-Dove",
    "Delichon urbicum": "Western House-Martin",
    "Lullula arborea": "Woodlark",
    "Alauda arvensis": "Eurasian Skylark",
    "Poecile montanus": "Willow Tit",
    "Poecile palustris": "Marsh Tit",
    "Luscinia megarhynchos": "Common Nightingale",
    "Turdus philomelos": "Song Thrush",
    "Turdus viscivorus": "Mistle Thrush",
    "Turdus pilaris": "Fieldfare",
    "Turdus iliacus": "Redwing",
    "Turdus torquatus": "Ring Ouzel",
    "Muscicapa striata": "Spotted Flycatcher",
    "Ficedula hypoleuca": "European Pied Flycatcher",
    "Saxicola rubetra": "Whinchat",
    "Locustella naevia": "Common Grasshopper Warbler",
    "Phylloscopus sibilatrix": "Wood Warbler",
    "Passer domesticus": "House Sparrow",
    "Passer montanus": "Eurasian Tree Sparrow",
    "Emberiza citrinella": "Yellowhammer",
    "Emberiza cirlus": "Cirl Bunting",
    "Emberiza calandra": "Corn Bunting",
    "Linaria cannabina": "Common Linnet",
    "Linaria flavirostris": "Twite",
    "Acanthis cabaret": "Lesser Redpoll",
    "Chloris chloris": "European Greenfinch",
    "Sturnus vulgaris": "European Starling",
    "Dryobates minor": "Lesser Spotted Woodpecker",
    "Coccothraustes coccothraustes": "Hawfinch",
    "Crex crex": "Corn Crake",
    "Vanellus vanellus": "Northern Lapwing",
    "Charadrius hiaticula": "Common Ringed Plover",
    "Numenius arquata": "Eurasian Curlew",
    "Numenius phaeopus": "Whimbrel",
    "Scolopax rusticola": "Eurasian Woodcock",
    "Limosa limosa": "Black-tailed Godwit",
    "Calidris alpina": "Dunlin",
    "Tringa totanus": "Common Redshank",
    "Fratercula arctica": "Atlantic Puffin",
    "Alca torda": "Razorbill",
    "Larus argentatus": "European Herring Gull",
    "Rissa tridactyla": "Black-legged Kittiwake",
    "Stercorarius parasiticus": "Parasitic Jaeger",
    "Sterna dougallii": "Roseate Tern",
    "Hydrobates leucorhous": "Leach's Storm-Petrel",
    "Aythya ferina": "Common Pochard",
    "Aythya marila": "Greater Scaup",
    "Melanitta nigra": "Common Scoter",
    "Melanitta fusca": "Velvet Scoter",
    "Clangula hyemalis": "Long-tailed Duck",
    "Tetrao urogallus": "Western Capercaillie",
    "Lyrurus tetrix": "Black Grouse",
    "Perdix perdix": "Grey Partridge",
    "Lagopus muta": "Rock Ptarmigan",
}


if __name__ == "__main__":
    sys.exit(main())
