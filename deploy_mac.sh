#!/bin/sh
# Build signed and notarized Apple Silicon and Intel application / DMG bundles.
# Export these credentials in your shell; never commit passwords or certificates.
set -eu
cd -- "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

: "${APPLE_SIGNING_IDENTITY:?Export your Developer ID Application signing identity}"
: "${APPLE_ID:?Export your Apple Account email address}"
: "${APPLE_TEAM_ID:?Export your Apple Developer Team ID}"
if [ -z "${APPLE_PASSWORD:-}" ]; then
  : "${APPLE_APP_SPECIFIC_PASSWORD:?Export APPLE_PASSWORD or APPLE_APP_SPECIFIC_PASSWORD for notarization}"
  APPLE_PASSWORD=$APPLE_APP_SPECIFIC_PASSWORD
  export APPLE_PASSWORD
fi
export CI=true

python3 scripts/import_release.py --check
if [ ! -x node_modules/.bin/tauri ]; then
  npm ci
fi
rustup target add x86_64-apple-darwin aarch64-apple-darwin
npx tauri build --target x86_64-apple-darwin --bundles app,dmg -- --locked
npx tauri build --target aarch64-apple-darwin --bundles app,dmg -- --locked
