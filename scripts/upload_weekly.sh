#!/usr/bin/env bash
# Weekly upload of detection audio + metadata to Google Drive.
#
# Uploads:
#   - /data/audio/**           (BirdNET-Go saves clips for detections >= threshold)
#   - /data/detections/birdnet.db               (full SQLite detection DB)
#   - /data/detections/birdnet-YYYY-WW.csv      (weekly CSV export)
#
# Verify-before-delete: captures a start-of-run audio manifest, uploads those
# files to Drive, confirms remote file size matches that same manifest via
# rclone check, then deletes only the verified manifest files. Never deletes
# unverified or newly-created audio.
#
# Usage:
#   upload_weekly.sh             # normal run
#   upload_weekly.sh --dry-run   # list actions, upload nothing, delete nothing

set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

REMOTE="${REMOTE:-gdrive:bird-call-monitoring}"
AUDIO_DIR="${AUDIO_DIR:-/data/audio}"
DETECTIONS_DIR="${DETECTIONS_DIR:-/data/detections}"
LOG_DIR="${LOG_DIR:-/data/logs}"
DB_PATH="${DETECTIONS_DIR}/birdnet.db"
INCLUDE_LOCATION="${INCLUDE_LOCATION:-0}"

WEEK_TAG="${WEEK_TAG:-$(date +%Y-W%V)}"
STAMP=$(date -Iseconds)
LOG_FILE="${LOG_DIR}/upload_${WEEK_TAG}.log"

log() { echo "[$(date -Iseconds)] $*" | tee -a "${LOG_FILE}" ; }

cleanup() {
    if [[ -n "${AUDIO_MANIFEST:-}" && -f "${AUDIO_MANIFEST}" ]]; then
        rm -f "${AUDIO_MANIFEST}"
    fi
}
trap cleanup EXIT

create_audio_manifest() {
    local audio_dir="$1"
    local manifest="$2"

    if [[ ! -d "${audio_dir}" ]]; then
        : > "${manifest}"
        return 0
    fi

    (
        cd "${audio_dir}"
        find . -type f -name '*.wav' -printf '%P\n' | sort > "${manifest}"
    )
}

manifest_count() {
    local manifest="$1"
    wc -l < "${manifest}"
}

validate_manifest_path() {
    local rel="$1"

    [[ -n "${rel}" ]] || return 1
    [[ "${rel}" != /* ]] || return 1
    [[ "${rel}" != "." ]] || return 1

    case "${rel}" in
        *$'\n'*|..|../*|*/../*|*/..)
            return 1
            ;;
    esac

    return 0
}

delete_manifest_files() {
    local audio_dir="$1"
    local manifest="$2"
    local rel

    while IFS= read -r rel; do
        [[ -n "${rel}" ]] || continue
        if ! validate_manifest_path "${rel}"; then
            log "ERROR: unsafe audio manifest path: ${rel}"
            exit 4
        fi
        if [[ -f "${audio_dir}/${rel}" ]]; then
            rm -f -- "${audio_dir}/${rel}"
        fi
    done < "${manifest}"

    find "${audio_dir}" -mindepth 1 -type d -empty -delete
}

mkdir -p "${LOG_DIR}"

log "=== Weekly upload start (dry-run=${DRY_RUN}) ==="

AUDIO_MANIFEST=$(mktemp "${LOG_DIR}/upload_${WEEK_TAG}_audio_manifest.XXXXXX")
create_audio_manifest "${AUDIO_DIR}" "${AUDIO_MANIFEST}"
log "Audio manifest: $(manifest_count "${AUDIO_MANIFEST}") WAV file(s) captured at upload start"

# 1. Export a fresh weekly CSV from SQLite.
#    Location columns are off by default. Set INCLUDE_LOCATION=1 only when you
#    are sure the export destination is appropriate for site/location data.
#    BirdNET-Go schema (nightly-20260418): detections table holds detection rows
#    with label_id; species scientific name is in labels table. Common names are
#    resolved via runtime locale file, not stored in SQL.
CSV_PATH="${DETECTIONS_DIR}/birdnet-${WEEK_TAG}.csv"
if [[ -f "${DB_PATH}" ]]; then
    log "Exporting CSV ${CSV_PATH}"
    if [[ "${INCLUDE_LOCATION}" == "1" ]]; then
        CSV_QUERY="SELECT datetime(d.detected_at,'unixepoch') AS ts_utc,
                l.scientific_name,
                d.confidence,
                d.clip_name,
                d.latitude,
                d.longitude,
                d.begin_time,
                d.end_time
         FROM detections d
         JOIN labels l ON l.id = d.label_id
         WHERE d.detected_at >= strftime('%s','now','-7 days')
         ORDER BY d.detected_at;"
    else
        CSV_QUERY="SELECT datetime(d.detected_at,'unixepoch') AS ts_utc,
                l.scientific_name,
                d.confidence,
                d.clip_name,
                d.begin_time,
                d.end_time
         FROM detections d
         JOIN labels l ON l.id = d.label_id
         WHERE d.detected_at >= strftime('%s','now','-7 days')
         ORDER BY d.detected_at;"
    fi
    sqlite3 -header -csv "${DB_PATH}" "${CSV_QUERY}" > "${CSV_PATH}"
    log "CSV rows: $(wc -l < "${CSV_PATH}")"
else
    log "WARNING: ${DB_PATH} not found - skipping CSV export"
fi

# 2. Check rclone is configured
REMOTE_NAME="${REMOTE%%:*}"
if ! rclone listremotes | grep -Fxq "${REMOTE_NAME}:"; then
    log "ERROR: rclone remote '${REMOTE_NAME}' not configured. See rclone/SETUP.md"
    exit 2
fi

# 3. Upload with progress + resume on failure
RCLONE_FLAGS=(--transfers=2 --checkers=4 --retries=5 --low-level-retries=10 \
              --log-file="${LOG_FILE}" --log-level=INFO)
if (( DRY_RUN )); then
    RCLONE_FLAGS+=(--dry-run)
fi

log "Upload: audio -> ${REMOTE}/audio/${WEEK_TAG}/"
rclone copy "${AUDIO_DIR}"       "${REMOTE}/audio/${WEEK_TAG}/"       --files-from-raw "${AUDIO_MANIFEST}" "${RCLONE_FLAGS[@]}"

log "Upload: detections -> ${REMOTE}/detections/${WEEK_TAG}/"
rclone copy "${DETECTIONS_DIR}"  "${REMOTE}/detections/${WEEK_TAG}/"  "${RCLONE_FLAGS[@]}"

if (( DRY_RUN )); then
    log "=== Dry run complete - no verification, no delete ==="
    exit 0
fi

# 4. Verify - rclone check exits non-zero if any manifest file is missing
#    or size mismatched. Files created after the manifest are left for the next run.
log "Verifying audio upload integrity against start-of-run manifest"
if ! rclone check "${AUDIO_DIR}" "${REMOTE}/audio/${WEEK_TAG}/" \
        --files-from-raw "${AUDIO_MANIFEST}" \
        --one-way --size-only --log-file="${LOG_FILE}" --log-level=INFO; then
    log "ERROR: audio verification failed - KEEPING local copies for manual review"
    exit 3
fi
log "Verified: all manifest audio files present and size-matched on remote"

# 5. Delete local audio (only after successful verify)
log "Deleting verified manifest audio clips"
delete_manifest_files "${AUDIO_DIR}" "${AUDIO_MANIFEST}"

# Leave SQLite DB in place (it's small, and BirdNET-Go keeps writing to it)
# Weekly CSV export is kept locally too; log rotation handles that.

log "=== Weekly upload complete ==="
