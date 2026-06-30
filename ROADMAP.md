# Roadmap

## Practical Summary

The project roadmap focuses on making low-cost Raspberry Pi passive acoustic monitoring easier to install, safer to maintain, and less likely to leak sensitive data.

## Near Term

- Add a tagged `0.1.x` release once install notes and CI have had one more review.
- Add optional systemd service and timer examples with clear dry-run steps.
- Add a setup preflight script for paths, env files, required packages, and writable output folders.
- Expand tests around upload manifests, location export, and missing-file handling.
- Add privacy-preserving sample fixtures for documentation and tests.
- Document common BirdNET-Go database and audio folder layouts.

## Medium Term

- Improve configuration validation and beginner-friendly error messages.
- Add optional notification backends beyond SMTP if they can be kept simple and secure.
- Add a small review workflow guide for checking priority species detections before sharing.
- Create release checklists covering tests, public-safety scans, documentation, and GitHub settings.

## Non-Goals

- Replacing BirdNET-Go species identification.
- Publishing real raw audio, exact monitoring locations, or private deployment details.
- Weakening verify-before-delete upload behaviour.
- Adding cloud services that require users to commit secrets to Git.
