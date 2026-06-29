# Security And Privacy Notes

## Practical Summary

Do not publish secrets, raw audio, exact site details, protected species locations, or land access information. Treat acoustic data as potentially sensitive, especially near homes, paths, gardens, reserves, farms, or protected species sites.

## Keep Out Of Git

Never commit:

- SMTP credentials or app passwords
- rclone config or cloud tokens
- SSH keys
- raw audio clips
- BirdNET-Go databases
- logs containing personal or site details
- exact coordinates or sensitive access notes

The included `.gitignore` blocks common risky file types, but you should still check before every public push.

## Location Data

The upload script excludes latitude and longitude from weekly CSV exports by default. Use `INCLUDE_LOCATION=1` only when you have a clear reason and the upload destination is appropriate.

## Audio Privacy

Bird call recordings can also capture people, addresses, conversations, vehicles, pets, or other identifying sounds. If you share examples publicly, crop and review them first.

## Safer Public Sharing

For public examples, prefer:

- short redacted clips
- synthetic or test fixtures
- screenshots without coordinates
- summary statistics instead of raw detections
- generic station labels

## If Something Sensitive Is Exposed

Make the repository private or remove it, rotate any exposed credentials, revoke cloud tokens, and republish from a fresh clean history. Deleting a file from the latest commit is not enough if it remains in Git history.
