# Security Policy

## Practical Summary

Please do not post secrets, raw audio, exact locations, or vulnerability details in public issues. This repository handles e-mail credentials, cloud uploads, acoustic data, and location-sensitive monitoring workflows, so privacy and data-loss risks matter.

## Supported Versions

This project is pre-1.0. Security fixes are made on `main` and included in the next release notes.

## Reporting A Concern

For private security reports, use GitHub's security reporting tools for this repository if available. If private reporting is not available, open a minimal public issue asking for a private contact route, but do not include exploit details, credentials, raw data, or sensitive site information.

For non-sensitive privacy or safety improvements, open a normal issue using the templates.

## What To Report

- exposed credentials, private keys, or cloud tokens
- unsafe upload or deletion behaviour
- accidental publication of raw audio, logs, databases, or locations
- path handling bugs that could read, overwrite, or delete unintended files
- documentation that encourages unsafe handling of secrets or sensitive field data

## Related Guidance

Read [docs/SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md) before using these scripts in a public or shared monitoring project.
