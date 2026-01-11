#!/bin/bash
# =============================================================================
# EmComm-Tools Update Publisher
# Version: 1.0.0
# Author: Sylvain Deguire (VA2OPS)
#
# Usage: ./publish.sh [version] [message]
# Example: ./publish.sh 1.0.1 "Fix et-update logging"
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default values
VERSION="${1:-1.0.0}"
MESSAGE="${2:-Update release $VERSION}"
CHANNEL="stable"
BASE_URL="https://raw.githubusercontent.com/emcomm-tools/updates/main/stable/files"

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  EmComm-Tools Update Publisher                                   ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║  Version: $VERSION"
echo "║  Channel: $CHANNEL"
echo "║  Message: $MESSAGE"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Check for files
FILE_COUNT=$(find stable/files -type f ! -name ".gitkeep" | wc -l)
echo "Files to publish: $FILE_COUNT"

if [ "$FILE_COUNT" -eq 0 ]; then
    echo "No files in stable/files/ - nothing to publish!"
    exit 1
fi

# Generate manifest
echo ""
echo "Generating manifest..."
./et-manifest-build \
    -s stable/files \
    -o stable/manifest.json \
    -v "$VERSION" \
    -c "$CHANNEL" \
    -u "$BASE_URL"

# Show what will be pushed
echo ""
echo "Changes to push:"
git status --short

# Confirm
echo ""
read -p "Push to GitHub? (y/N): " confirm
if [ "${confirm,,}" != "y" ]; then
    echo "Cancelled."
    exit 0
fi

# Git commit and push
git add .
git commit -m "$MESSAGE"
git push

echo ""
echo "✓ Published version $VERSION"
echo ""
echo "Users can now run: et-update"
