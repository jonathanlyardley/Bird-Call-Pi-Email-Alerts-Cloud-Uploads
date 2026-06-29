#!/usr/bin/env bash
set -euo pipefail

echo "== shell syntax =="
find scripts tests -name '*.sh' -print0 | xargs -0 -r bash -n

echo
echo "== ignored risky patterns =="
required_patterns=(
  "*.wav"
  "*.flac"
  "*.mp3"
  "*.db"
  "*.sqlite"
  "*.sqlite3"
  "*.log"
  ".env"
  ".env.*"
  "*.pem"
  "*.key"
  "secrets/"
  "audio/"
  "clips/"
  "detections/"
  "data/"
  "*.tar.gz"
  "*.zip"
)

missing=0
for pattern in "${required_patterns[@]}"; do
    if ! grep -Fqx "${pattern}" .gitignore; then
        echo "Missing .gitignore pattern: ${pattern}" >&2
        missing=1
    fi
done
if [[ "${missing}" -ne 0 ]]; then
    exit 1
fi

echo
echo "== tracked file safety =="
if git ls-files | grep -E '\.(wav|flac|mp3|aac|ogg|db|sqlite|sqlite3|log|pem|key|ppk|zip)$|\.tar\.gz$|(^|/)rclone\.conf$|(^|/)secrets/' >/tmp/public-repo-bad-files.txt; then
    cat /tmp/public-repo-bad-files.txt >&2
    rm -f /tmp/public-repo-bad-files.txt
    exit 1
fi
rm -f /tmp/public-repo-bad-files.txt

echo
echo "== sensitive text scan =="
git ls-files -z \
    | xargs -0 grep -InE 'BEGIN (RSA |OPENSSH |DSA |EC )?PRIVATE KE[Y]|refresh[_]token|client[_]secret|rclone[.]conf|192[.]168[.]|/home/pa[m]|/opt/bird_pa[m]|St Pamd[y]|Salis[b]ury' \
    | grep -v '^.gitignore:' \
    >/tmp/public-repo-sensitive-text.txt || true
if [[ -s /tmp/public-repo-sensitive-text.txt ]]; then
    cat /tmp/public-repo-sensitive-text.txt >&2
    rm -f /tmp/public-repo-sensitive-text.txt
    exit 1
fi
rm -f /tmp/public-repo-sensitive-text.txt

echo
echo "Public repository checks passed."
