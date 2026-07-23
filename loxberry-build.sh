#!/bin/bash
# Build script for packaging smtp2mqtt into a LoxBerry Plugin ZIP archive

set -e

PLUGIN_NAME="smtp2mqtt"
VERSION=$(grep -i '^VERSION=' plugin.cfg | head -n 1 | cut -d'=' -f2 | tr -d '\r ')
if [ -z "$VERSION" ]; then
    VERSION="1.7.0"
fi
ZIP_NAME="${PLUGIN_NAME}-loxberry-v${VERSION}.zip"

echo "📦 Packaging LoxBerry Plugin: ${ZIP_NAME}..."

# Remove old build if present
rm -f "${ZIP_NAME}"

# Ensure executable bits
chmod +x postinstall.sh preupgrade.sh postupgrade.sh preremove.sh smtp2mqtt.py 2>/dev/null || true

# Build ZIP archive
zip -r "${ZIP_NAME}" \
    plugin.cfg \
    release.cfg \
    prerelease.cfg \
    postinstall.sh \
    preupgrade.sh \
    postupgrade.sh \
    preremove.sh \
    smtp2mqtt.py \
    requirements.txt \
    favicon.svg \
    logo.svg \
    icons/ \
    webfrontend/ \
    -x "*.pyc" "__pycache__/*" ".git/*" ".venv/*" ".pytest_cache/*" "tests/*" "deploy/*" "docs/*" ".coverage"

echo "✅ Build completed successfully: ${ZIP_NAME}"
