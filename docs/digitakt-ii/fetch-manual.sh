#!/bin/sh
# Download the official Digitakt II user manual (OS 1.17) next to this script and check its hash.
# The PDF is Elektron's copyright and is not redistributed in this repo (see README.md here).
set -eu
cd "$(dirname "$0")"
URL="https://www.elektron.se/wp-content/uploads/2026/10/Digitakt-2-User-Manual_ENG_OS1.17_260930.pdf"
FILE="Digitakt-2-User-Manual_ENG_OS1.17_260930.pdf"
SHA256="a5c12b2b692311828f78fad18008dcda96bf26dd50e117bda5d735794e0bbd06"
curl -fsSL -o "$FILE" "$URL"
if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$FILE" | cut -d' ' -f1)
else got=$(shasum -a 256 "$FILE" | cut -d' ' -f1); fi
if [ "$got" != "$SHA256" ]; then
  echo "SHA-256 mismatch: got $got, expected $SHA256 (Elektron may have reissued the manual;" >&2
  echo "check the page numbers in reference.md against the new edition)" >&2
  exit 1
fi
echo "OK: $FILE"
