#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="${repo_root}/scripts/upload_weekly.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_file() {
    [[ -f "$1" ]] || fail "expected file to exist: $1"
}

assert_not_file() {
    [[ ! -f "$1" ]] || fail "expected file to be absent: $1"
}

# Safety gate: the old script ignores test directories and would operate on
# /data/audio, so fail before executing unless the manifest implementation is present.
grep -q 'create_audio_manifest' "${script}" || fail "upload script has no start-of-run audio manifest"
grep -q -- '--files-from-raw' "${script}" || fail "upload script does not pass the manifest to rclone"
grep -Fq -- '-mindepth 1 -type d -empty -delete' "${script}" || fail "upload script may delete the audio root directory"
if grep -q 'find "${AUDIO_DIR}" -type f -name '\''\*.wav'\'' -delete' "${script}"; then
    fail "upload script still has broad WAV deletion"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

audio="${tmp}/audio"
detections="${tmp}/detections"
logs="${tmp}/logs"
remote_root="${tmp}/remote"
bin="${tmp}/bin"
mkdir -p "${audio}/2026/06" "${detections}" "${logs}" "${remote_root}" "${bin}"

printf 'old-a\n' > "${audio}/2026/06/old_a.wav"
printf 'old-b\n' > "${audio}/2026/06/old_b.wav"

cat > "${bin}/rclone" <<'RCLONE'
#!/usr/bin/env bash
set -euo pipefail

to_path() {
    local value="$1"
    if [[ "${value}" == gdrive:* ]]; then
        printf '%s\n' "${value#gdrive:}"
    else
        printf '%s\n' "${value}"
    fi
}

find_files_from_raw() {
    local arg
    while (($#)); do
        arg="$1"
        shift
        if [[ "${arg}" == "--files-from-raw" ]]; then
            printf '%s\n' "$1"
            return 0
        fi
    done
    return 1
}

cmd="${1:-}"
shift || true

case "${cmd}" in
    listremotes)
        echo "gdrive:"
        ;;
    copy)
        src="$1"
        dst="$(to_path "$2")"
        shift 2
        mkdir -p "${dst}"
        if manifest="$(find_files_from_raw "$@")"; then
            while IFS= read -r rel; do
                [[ -n "${rel}" ]] || continue
                mkdir -p "${dst}/$(dirname "${rel}")"
                cp "${src}/${rel}" "${dst}/${rel}"
            done < "${manifest}"
            printf 'late\n' > "${src}/2026/06/new_during_upload.wav"
        else
            cp -a "${src}/." "${dst}/"
        fi
        ;;
    check)
        src="$1"
        dst="$(to_path "$2")"
        shift 2
        manifest="$(find_files_from_raw "$@")"
        while IFS= read -r rel; do
            [[ -n "${rel}" ]] || continue
            [[ -f "${dst}/${rel}" ]] || exit 1
            [[ "$(wc -c < "${src}/${rel}")" == "$(wc -c < "${dst}/${rel}")" ]] || exit 1
        done < "${manifest}"
        ;;
    *)
        echo "unexpected rclone command: ${cmd}" >&2
        exit 64
        ;;
esac
RCLONE
chmod +x "${bin}/rclone"

PATH="${bin}:${PATH}" \
REMOTE="gdrive:${remote_root}" \
AUDIO_DIR="${audio}" \
DETECTIONS_DIR="${detections}" \
LOG_DIR="${logs}" \
WEEK_TAG="2026-W99" \
"${script}"

assert_not_file "${audio}/2026/06/old_a.wav"
assert_not_file "${audio}/2026/06/old_b.wav"
assert_file "${audio}/2026/06/new_during_upload.wav"
assert_file "${remote_root}/audio/2026-W99/2026/06/old_a.wav"
assert_file "${remote_root}/audio/2026-W99/2026/06/old_b.wav"
assert_not_file "${remote_root}/audio/2026-W99/2026/06/new_during_upload.wav"

echo "PASS: upload manifest protects new files created during upload"
