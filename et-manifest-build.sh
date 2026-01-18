#!/bin/bash
# =============================================================================
# et-manifest-build - Generate manifest.json from overlay files
# Version: 1.1.0
# Updated: 2026-01-18
# Author: Sylvain Deguire (VA2OPS)
#
# Developer tool to generate manifest for update server
# Fixed: Handle Python files and various version formats
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

show_help() {
    cat << EOF
EmComm-Tools Manifest Builder

Usage: et-manifest-build [OPTIONS] -s SOURCE_DIR -o OUTPUT_FILE

Options:
  -s, --source DIR     Source directory (overlay folder)
  -o, --output FILE    Output manifest file (manifest.json)
  -v, --version VER    Version string (e.g., 1.0.0)
  -c, --channel CHAN   Channel name (stable, beta, personal)
  -u, --url URL        Base URL for file downloads
  -h, --help           Show this help message

Examples:
  et-manifest-build -s ./personal/files -o ./personal/manifest.json -v 1.0.0 -c personal
  et-manifest-build -s ./personal/files \\
                    -o ./personal/manifest.json \\
                    -v 1.4.3 \\
                    -c personal \\
                    -u https://raw.githubusercontent.com/emcomm-tools/updates/main/personal/files

EOF
}

extract_version_from_file() {
    local file="$1"
    local version=""
    
    # Try multiple patterns for version extraction
    # Pattern 1: Bash style "# Version: 1.0.0"
    version=$(grep -m1 -i "^# Version:" "$file" 2>/dev/null | sed 's/^# Version:[[:space:]]*//' | awk '{print $1}' | tr -d '[:space:]')
    
    # Pattern 2: Python docstring style "Version: 1.0.56 - ..."
    if [ -z "$version" ]; then
        version=$(grep -m1 -i "^Version:" "$file" 2>/dev/null | sed 's/^Version:[[:space:]]*//' | awk '{print $1}' | tr -d '[:space:]')
    fi
    
    # Pattern 3: VERSION = "1.0.0" or __version__ = "1.0.0"
    if [ -z "$version" ]; then
        version=$(grep -m1 -iE "^(VERSION|__version__)[[:space:]]*=" "$file" 2>/dev/null | sed 's/.*=[[:space:]]*["'"'"']//' | sed 's/["'"'"'].*//' | tr -d '[:space:]')
    fi
    
    # Fallback: use file modification date
    if [ -z "$version" ]; then
        version=$(date -r "$file" '+%Y.%m.%d')
    fi
    
    echo "$version"
}

extract_description_from_file() {
    local file="$1"
    local description=""
    
    # Pattern 1: Bash style "# Purpose: ..."
    description=$(grep -m1 -i "^# Purpose:" "$file" 2>/dev/null | sed 's/^# Purpose:[[:space:]]*//')
    
    # Pattern 2: Python docstring - get first line after """
    if [ -z "$description" ]; then
        description=$(sed -n '/^"""/,/^"""/p' "$file" 2>/dev/null | sed -n '2p' | sed 's/^[[:space:]]*//')
    fi
    
    # Fallback: empty
    if [ -z "$description" ]; then
        description=""
    fi
    
    echo "$description"
}

get_permissions() {
    local file="$1"
    stat -c "%a" "$file"
}

generate_manifest() {
    local source_dir="$1"
    local output_file="$2"
    local version="$3"
    local channel="$4"
    local base_url="$5"
    
    echo -e "${GREEN}[INFO]${NC} Scanning: $source_dir"
    echo -e "${GREEN}[INFO]${NC} Output:   $output_file"
    echo -e "${GREEN}[INFO]${NC} Version:  $version"
    echo -e "${GREEN}[INFO]${NC} Channel:  $channel"
    echo ""
    
    local temp_files="/tmp/manifest-files-$$.json"
    echo "[]" > "$temp_files"
    
    local file_count=0
    
    # Find all files in source directory
    while IFS= read -r -d '' file; do
        # Skip certain files
        local basename=$(basename "$file")
        case "$basename" in
            *.pyc|*.pyo|__pycache__|.git*|*.swp|*.bak|.DS_Store)
                continue
                ;;
        esac
        
        # Skip __pycache__ directories
        if [[ "$file" == *"__pycache__"* ]]; then
            continue
        fi
        
        # Get relative path
        local rel_path="${file#$source_dir/}"
        
        # Calculate checksum
        local sha256=$(sha256sum "$file" | cut -d' ' -f1)
        
        # Get file size
        local size=$(stat -c "%s" "$file")
        
        # Get permissions
        local permissions=$(get_permissions "$file")
        
        # Get file version (with error handling)
        local file_version
        file_version=$(extract_version_from_file "$file") || file_version="$version"
        
        # Get description from file header (with error handling)
        local description
        description=$(extract_description_from_file "$file") || description=""
        
        # Escape special characters for JSON
        description=$(echo "$description" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed 's/\t/ /g' | tr -d '\n\r')
        
        echo -e "  ${BLUE}[SCAN]${NC} $rel_path (v$file_version)"
        
        # Add to JSON array using jq with proper error handling
        if ! jq --arg path "$rel_path" \
           --arg version "$file_version" \
           --arg sha256 "$sha256" \
           --argjson size "$size" \
           --arg permissions "$permissions" \
           --arg description "$description" \
           '. += [{
               "path": $path,
               "version": $version,
               "sha256": $sha256,
               "size": $size,
               "permissions": $permissions,
               "description": $description
           }]' "$temp_files" > "${temp_files}.tmp" 2>/dev/null; then
            echo -e "  ${YELLOW}[WARN]${NC} Failed to add $rel_path to manifest, skipping..."
            continue
        fi
        
        mv "${temp_files}.tmp" "$temp_files"
        file_count=$((file_count + 1))
        
    done < <(find "$source_dir" -type f -print0 | sort -z)
    
    echo ""
    echo -e "${GREEN}[INFO]${NC} Found $file_count files"
    
    # Build final manifest
    local release_date=$(date '+%Y-%m-%d')
    
    jq -n \
        --arg schema_version "1.0" \
        --arg distribution "EmComm-Tools Debian Edition" \
        --arg version "$version" \
        --arg channel "$channel" \
        --arg release_date "$release_date" \
        --arg base_url "$base_url" \
        --slurpfile files "$temp_files" \
        '{
            "schema_version": $schema_version,
            "distribution": $distribution,
            "version": $version,
            "channel": $channel,
            "release_date": $release_date,
            "base_url": $base_url,
            "files": $files[0]
        }' > "$output_file"
    
    rm -f "$temp_files"
    
    echo -e "${GREEN}[INFO]${NC} Manifest created: $output_file"
    echo ""
    
    # Show summary
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  Manifest Summary                                                ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    printf "║  Version:      %-51s║\n" "$version"
    printf "║  Channel:      %-51s║\n" "$channel"
    printf "║  Files:        %-51s║\n" "$file_count"
    printf "║  Release Date: %-51s║\n" "$release_date"
    echo "╚══════════════════════════════════════════════════════════════════╝"
}

# =============================================================================
# Main
# =============================================================================
main() {
    local source_dir=""
    local output_file=""
    local version="1.0.0"
    local channel="stable"
    local base_url="https://raw.githubusercontent.com/emcomm-tools/updates/main/stable/files"
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            -s|--source)
                source_dir="$2"
                shift 2
                ;;
            -o|--output)
                output_file="$2"
                shift 2
                ;;
            -v|--version)
                version="$2"
                shift 2
                ;;
            -c|--channel)
                channel="$2"
                shift 2
                ;;
            -u|--url)
                base_url="$2"
                shift 2
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                echo -e "${RED}[ERROR]${NC} Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # Validate required arguments
    if [ -z "$source_dir" ]; then
        echo -e "${RED}[ERROR]${NC} Source directory required (-s)"
        show_help
        exit 1
    fi
    
    if [ -z "$output_file" ]; then
        echo -e "${RED}[ERROR]${NC} Output file required (-o)"
        show_help
        exit 1
    fi
    
    if [ ! -d "$source_dir" ]; then
        echo -e "${RED}[ERROR]${NC} Source directory not found: $source_dir"
        exit 1
    fi
    
    # Check for jq
    if ! command -v jq &> /dev/null; then
        echo -e "${RED}[ERROR]${NC} jq is required but not installed"
        echo "Install with: sudo apt install jq"
        exit 1
    fi
    
    generate_manifest "$source_dir" "$output_file" "$version" "$channel" "$base_url"
}

main "$@"
