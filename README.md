# Bird Call Pi Email Alerts and Cloud Uploads

## Practical Summary

Field-tested Raspberry Pi scripts for BirdNET-Go users who want a customisable bird-call e-mail alert, with confidence thresholds, attached audio clips, call isolation in bird call choruses, and safer cloud uploads that verify files before deleting local WAVs to ensure memory cards do not fill.

## What This Is Useful For

- Passive acoustic monitoring with a Raspberry Pi and BirdNET-Go.
- Getting e-mail alerts for chosen priority species.
- Attaching original WAV clips and optional filtered review FLACs to alerts.
- Creating review packages with copied original audio, filtered listening aids, spectrograms, metadata, and a review log.
- Uploading audio and detections to an rclone remote while protecting newly-created files during long uploads.

## Safety Defaults

- Secrets stay outside Git in an env file.
- Raw audio, logs, databases, archives, keys, and data folders are ignored.
- Weekly upload uses a start-of-run WAV manifest, verifies the uploaded files, then deletes only verified manifest files.
- Location columns are excluded from weekly CSV exports by default. Set `INCLUDE_LOCATION=1` only if your destination is appropriate for location data.

## Main Scripts

| File | Purpose |
| --- | --- |
| `scripts/alert_poller.py` | Polls a BirdNET-Go SQLite database for new high-confidence priority species and triggers e-mail alerts. |
| `scripts/alert_email.py` | Sends an e-mail with the original WAV and, when available, a filtered review FLAC. |
| `scripts/review_artifacts.py` | Builds review artefacts for selected detections. Requires `ffmpeg` and `sox` for audio/spectrogram outputs. |
| `scripts/upload_weekly.sh` | Uploads audio and detections through rclone with verify-before-delete behaviour for audio. |

## Quick Start

1. Install BirdNET-Go on your Raspberry Pi and confirm it is saving detections and WAV clips.
2. Copy `examples/email.env.example` to an env file outside the repository, for example `/opt/bird-call-alerts/secrets/email.env`.
3. Fill in your SMTP details and `PRIORITY_SPECIES`.
4. Run the poller manually once before adding timers:

```bash
python3 scripts/alert_poller.py
```

5. Dry-run the upload script before enabling it:

```bash
bash scripts/upload_weekly.sh --dry-run
```

See [docs/INSTALL.md](docs/INSTALL.md) for setup notes and [docs/SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md) before making a public deployment.

## Configuration

Useful environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BIRD_CALL_EMAIL_ENV` | `/opt/bird-call-alerts/secrets/email.env` | Path to the e-mail env file. |
| `BIRD_CALL_STATION_LABEL` | `Bird monitoring station` | Generic label used in e-mail subjects/bodies. Can also be set as `STATION_LABEL` inside the env file. |
| `BIRD_CALL_DB_PATH` | `/data/detections/birdnet.db` | BirdNET-Go SQLite database. |
| `BIRD_CALL_AUDIO_DIR` | `/data/audio` | BirdNET-Go WAV clip root. |
| `BIRD_CALL_REVIEW_DIR` | `/data/review` | Review artefact root. |
| `REMOTE` | `gdrive:bird-call-monitoring` | rclone remote/path used by `upload_weekly.sh`. |
| `AUDIO_DIR` | `/data/audio` | Upload script audio root. |
| `DETECTIONS_DIR` | `/data/detections` | Upload script detection/database root. |
| `LOG_DIR` | `/data/logs` | Upload script log root. |
| `INCLUDE_LOCATION` | `0` | Set to `1` to include latitude/longitude in weekly CSV exports. |

## Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
bash tests/test_upload_weekly.sh
bash scripts/check-public-repo.sh
```

## Licence

MIT. Use it, adapt it, and improve it, but review the safety/privacy notes first.
