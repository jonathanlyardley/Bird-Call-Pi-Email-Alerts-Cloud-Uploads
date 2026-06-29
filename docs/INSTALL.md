# Install Notes

## Practical Summary

These scripts assume BirdNET-Go is already running and writing a SQLite database plus WAV clips. Start with manual dry runs, then add systemd timers or cron only once paths, e-mail, and rclone are confirmed.

## Raspberry Pi Packages

On Raspberry Pi OS, the scripts expect:

```bash
sudo apt update
sudo apt install -y python3 sqlite3 rclone ffmpeg sox
```

`ffmpeg` and `sox` are only needed for review artefacts. E-mail alerts and upload checks can work without review artefact generation.

## E-mail Env File

Copy the example file outside the repository:

```bash
sudo mkdir -p /opt/bird-call-alerts/secrets
sudo cp examples/email.env.example /opt/bird-call-alerts/secrets/email.env
sudo chmod 600 /opt/bird-call-alerts/secrets/email.env
```

Edit the copy with your real values. Do not commit it.

## Manual Checks

Run these before installing timers:

```bash
BIRD_CALL_EMAIL_ENV=/opt/bird-call-alerts/secrets/email.env python3 scripts/alert_poller.py
bash scripts/upload_weekly.sh --dry-run
```

For review artefacts:

```bash
python3 scripts/review_artifacts.py --dry-run --since-hours 48 --limit 20
```

## Scheduling

Use systemd timers or cron after manual checks are clean. Keep timer commands explicit about env-file paths and data paths if your BirdNET-Go installation differs from the defaults.

## Upload Safety

`scripts/upload_weekly.sh` is designed to protect audio created during a long upload:

- it captures a start-of-run WAV manifest
- uploads only that manifest
- verifies those same files on the remote
- deletes only verified manifest files
- leaves newer WAVs for the next run

Run `--dry-run` after changing paths, rclone remotes, or schedules.
