#!/usr/bin/env bash
# Verify a built Flatpak image, its distributable bundle, and a fresh user install.
set -euo pipefail

APP_ID="io.github.dusten45.MDLogger"
PROJECT_ROOT=""
BUILD_DIRECTORY=""
REPOSITORY=""
BUNDLE=""
VERSION=""
RECORD=""
INSTALLED=0

usage() {
  echo "usage: $0 --project-root DIR --build-dir DIR --repo DIR --bundle FILE --version X.Y.Z --record FILE" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --build-dir)
      BUILD_DIRECTORY="$2"
      shift 2
      ;;
    --repo)
      REPOSITORY="$2"
      shift 2
      ;;
    --bundle)
      BUNDLE="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --record)
      RECORD="$2"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$PROJECT_ROOT" || -z "$BUILD_DIRECTORY" || -z "$REPOSITORY" || -z "$BUNDLE" || -z "$VERSION" || -z "$RECORD" ]]; then
  usage
  exit 2
fi
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "version must use X.Y.Z" >&2
  exit 2
fi
if [[ "$(basename "$BUNDLE")" != "MDLogger-$VERSION.flatpak" ]]; then
  echo "unexpected Flatpak bundle filename: $BUNDLE" >&2
  exit 2
fi

cleanup() {
  if [[ "$INSTALLED" == "1" ]]; then
    flatpak uninstall --user --noninteractive --assumeyes "$APP_ID" || true
  fi
}
trap cleanup EXIT

cd "$PROJECT_ROOT"
uv run python scripts/verify_flatpak_license_payload.py \
  --app-root "$BUILD_DIRECTORY/files" \
  --payload-phase final_image
uv run python -m mdlogger.secret_scan "$BUILD_DIRECTORY/files"

flatpak build-bundle "$REPOSITORY" "$BUNDLE" "$APP_ID"
uv run python -m mdlogger.checksum "$BUNDLE"

# Each GitHub runner starts with a fresh user Flatpak installation. Installing into
# that user repository validates the generated bundle rather than the builder tree.
flatpak install --user --noninteractive --assumeyes "$BUNDLE"
INSTALLED=1
flatpak run --user --command=sh "$APP_ID" -c '
  test -x /app/bin/mdlogger && \
  test -f /app/share/licenses/mdlogger/LICENSE && \
  test -f /app/share/doc/mdlogger/THIRD_PARTY_NOTICES.txt && \
  test -f /app/share/licenses/mdlogger/inventory/desktop-linux.json && \
  test -f /app/share/licenses/mdlogger/inventory/qt-modules-linux-flatpak.json && \
  test -f /app/share/licenses/mdlogger/inventory/qt-third-party-runtime-linux-flatpak.json && \
  test ! -e /app/share/licenses/mdlogger/inventory/desktop-windows.json && \
  test -f /app/share/doc/mdlogger/sources/desktop-source-offer.md && \
  test ! -e /app/venv/lib/python3.13/site-packages/pip && \
  test ! -e /app/venv/bin/pip && \
  test ! -e /app/venv/lib/python3.13/site-packages/pyqtgraph/colors/maps/PAL-relaxed.hex && \
  test ! -e /app/venv/lib/python3.13/site-packages/pyqtgraph/colors/maps/PAL-relaxed_bright.hex
'

python_version="$(uv run python --version)"
uv_version="$(uv --version)"
flatpak_version="$(flatpak --version)"
builder_version="$(flatpak-builder --version)"
runtime_ref="$(flatpak info --user --show-runtime "$APP_ID")"
runtime_commit="$(flatpak info --user --show-commit "$runtime_ref")"
sdk_commit="$(flatpak info --user --show-commit org.freedesktop.Sdk//25.08)"

uv run python scripts/release/create_release_manifest.py platform-record \
  --platform linux-flatpak-x86_64 \
  --asset "$BUNDLE" \
  --output "$RECORD" \
  --check final-image-license-payload \
  --check final-image-secret-scan \
  --check bundle-checksum \
  --check bundle-installation \
  --check installed-license-payload \
  --check installed-entry-point \
  --tool "python=$python_version" \
  --tool "uv=$uv_version" \
  --tool "flatpak=$flatpak_version" \
  --tool "flatpak-builder=$builder_version" \
  --tool "runtime=$runtime_ref" \
  --tool "runtime-commit=$runtime_commit" \
  --tool "sdk-commit=$sdk_commit" \
  --tool "runner-os=${RUNNER_OS:-unknown}" \
  --tool "runner-image-version=${ImageVersion:-unknown}"
