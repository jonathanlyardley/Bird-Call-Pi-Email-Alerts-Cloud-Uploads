# Contributing

## Practical Summary

Contributions are welcome, especially improvements that make Raspberry Pi setup safer, clearer, and easier to test. Keep changes small, avoid publishing sensitive field data, and preserve the verify-before-delete upload behaviour.

## Good First Contributions

- clearer install notes for Raspberry Pi OS
- tests for edge cases in alerting, review artefacts, or uploads
- safer defaults and better validation messages
- documentation for common BirdNET-Go layouts
- small bug fixes that improve reliability on low-cost hardware

## Do Not Include

- SMTP passwords, app passwords, cloud tokens, or private keys
- raw audio clips, real detections databases, or logs
- exact coordinates, protected species locations, access notes, or landowner details
- hard-coded personal paths, station names, or deployment-specific assumptions

## Local Checks

Run these before opening a pull request:

```bash
python3 -m unittest discover -s tests -p "test_*.py"
bash tests/test_upload_weekly.sh
bash scripts/check-public-repo.sh
```

## Pull Request Checklist

- Configuration is passed through env files or command options, not hard-coded.
- New tests or docs cover the change.
- Alert e-mails keep station labels generic or configurable.
- Location export remains opt-in.
- Upload changes keep verify-before-delete behaviour.
- No secrets, raw audio, logs, databases, archives, or exact site details are tracked.

## Maintainer Notes

This project favours squash merges, passing CI, and practical release notes over large unreviewed changes. Please open an issue first for changes that affect deletion, upload verification, credentials, privacy, or expected BirdNET-Go paths.
