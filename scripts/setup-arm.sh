#!/usr/bin/env bash
# ARM Setup Script - Configure ARM for external transcoding via arm-transcoder
#
# Patches an existing ARM arm.yaml to disable built-in transcoding and
# configure webhook notifications to arm-transcoder. Optionally deploys
# the authenticated notify_transcoder.sh script.
#
# Usage:
#   ./setup-arm.sh --url URL --config DIR [--secret SECRET] [--local-raw PATH] [--nfs-raw PATH] [--restart]
#
# Examples:
#   # Simple webhook (no auth)
#   ./setup-arm.sh --url http://TRANSCODER_IP:5000/webhook/arm --config /etc/arm/config
#
#   # Authenticated webhook
#   ./setup-arm.sh --url http://TRANSCODER_IP:5000/webhook/arm --config /etc/arm/config --secret myS3cret
#
#   # Local scratch storage (rip to local disk, move to NFS before transcoding)
#   ./setup-arm.sh --url http://TRANSCODER_IP:5000/webhook/arm --config /etc/arm/config \
#     --secret myS3cret --local-raw /home/arm/media/raw --nfs-raw /nfs/files/Video/Import/raw
#
#   # Docker ARM with container restart
#   ./setup-arm.sh --url http://TRANSCODER_IP:5000/webhook/arm --config /opt/arm/config --secret myS3cret --restart

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NOTIFY_TEMPLATE="$REPO_DIR/config/arm/notify_transcoder.sh"

# --- Defaults ---
TRANSCODER_URL=""
ARM_CONFIG_DIR=""
WEBHOOK_SECRET=""
LOCAL_RAW_PATH=""
NFS_RAW_PATH=""
RESTART=false

# --- Usage ---
usage() {
    cat <<EOF
Usage: $(basename "$0") --url URL --config DIR [--secret SECRET] [--local-raw PATH] [--nfs-raw PATH] [--restart]

Configure an ARM installation for external transcoding via arm-transcoder.

Required:
  --url URL           Transcoder webhook URL (e.g. http://TRANSCODER_IP:5000/webhook/arm)
  --config DIR        Path to ARM config directory containing arm.yaml

Optional:
  --secret SECRET     Webhook secret — deploys notify_transcoder.sh for authenticated webhooks
  --local-raw PATH    Local disk path where ARM rips to (e.g. /home/arm/media/raw)
  --nfs-raw PATH      NFS path for handoff to transcoder (e.g. /nfs/files/Video/Import/raw)
  --restart           Restart ARM after setup (tries Docker first, then systemd)
  -h, --help          Show this help

When --local-raw and --nfs-raw are both provided, the notify script will move
ripped files from local disk to NFS before sending the webhook. This requires
--secret mode (BASH_SCRIPT).
EOF
    exit "${1:-0}"
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)
            TRANSCODER_URL="$2"
            shift 2
            ;;
        --config)
            ARM_CONFIG_DIR="$2"
            shift 2
            ;;
        --secret)
            WEBHOOK_SECRET="$2"
            shift 2
            ;;
        --local-raw)
            LOCAL_RAW_PATH="$2"
            shift 2
            ;;
        --nfs-raw)
            NFS_RAW_PATH="$2"
            shift 2
            ;;
        --restart)
            RESTART=true
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage 1
            ;;
    esac
done

# --- Validate inputs ---
if [[ -z "$TRANSCODER_URL" ]]; then
    echo "ERROR: --url is required" >&2
    usage 1
fi

if [[ -z "$ARM_CONFIG_DIR" ]]; then
    echo "ERROR: --config is required" >&2
    usage 1
fi

ARM_YAML="$ARM_CONFIG_DIR/arm.yaml"
if [[ ! -f "$ARM_YAML" ]]; then
    echo "ERROR: arm.yaml not found at $ARM_YAML" >&2
    echo "       Make sure --config points to the ARM config directory." >&2
    exit 1
fi

# Validate local-raw / nfs-raw pairing
if [[ -n "$LOCAL_RAW_PATH" && -z "$NFS_RAW_PATH" ]] || [[ -z "$LOCAL_RAW_PATH" && -n "$NFS_RAW_PATH" ]]; then
    echo "ERROR: --local-raw and --nfs-raw must be used together" >&2
    usage 1
fi

# Local scratch requires BASH_SCRIPT mode (needs the move logic in notify script)
if [[ -n "$LOCAL_RAW_PATH" && -z "$WEBHOOK_SECRET" ]]; then
    echo "ERROR: --local-raw/--nfs-raw requires --secret (BASH_SCRIPT mode)" >&2
    echo "       The notify script must be deployed to handle the local→NFS move." >&2
    usage 1
fi

echo "=== ARM Setup for arm-transcoder ==="
echo "Transcoder URL: $TRANSCODER_URL"
echo "ARM config:     $ARM_CONFIG_DIR"
echo "Auth mode:      $(if [[ -n "$WEBHOOK_SECRET" ]]; then echo "BASH_SCRIPT (authenticated)"; else echo "JSON_URL (simple)"; fi)"
if [[ -n "$LOCAL_RAW_PATH" ]]; then
    echo "Local scratch:  $LOCAL_RAW_PATH → $NFS_RAW_PATH"
fi
echo ""

# --- Helper: patch a YAML key ---
# Sets KEY: VALUE in arm.yaml. If the key exists (uncommented), replaces it.
# If the key only exists commented out, uncomments the first occurrence.
# If the key doesn't exist at all, appends it.
patch_yaml() {
    local key="$1"
    local value="$2"
    local file="$ARM_YAML"

    if grep -qE "^${key}:" "$file"; then
        # Key exists uncommented — replace it
        sed -i "s|^${key}:.*|${key}: ${value}|" "$file"
    elif grep -qE "^#\s*${key}:" "$file"; then
        # Key exists only as comment — uncomment and set value (first occurrence)
        sed -i "0,/^#\s*${key}:.*/s||${key}: ${value}|" "$file"
    else
        # Key doesn't exist — append it
        echo "${key}: ${value}" >> "$file"
    fi
}

# --- Patch transcoding settings ---
echo "Patching arm.yaml..."

patch_yaml "SKIP_TRANSCODE" "true"
patch_yaml "RIPMETHOD" '"mkv"'
patch_yaml "DELRAWFILES" "false"
patch_yaml "MAX_CONCURRENT_TRANSCODES" "0"
patch_yaml "NOTIFY_RIP" "true"
patch_yaml "NOTIFY_TRANSCODE" "false"

echo "  SKIP_TRANSCODE: true"
echo "  RIPMETHOD: \"mkv\""
echo "  DELRAWFILES: false"
echo "  MAX_CONCURRENT_TRANSCODES: 0"
echo "  NOTIFY_RIP: true"
echo "  NOTIFY_TRANSCODE: false"

# --- Configure notification method ---
if [[ -n "$WEBHOOK_SECRET" ]]; then
    # Authenticated mode: deploy notify_transcoder.sh + set BASH_SCRIPT
    echo ""
    echo "Deploying notify_transcoder.sh..."

    # Determine script deploy location
    SCRIPT_DEPLOY_DIR="/home/arm/scripts"
    if [[ ! -d "$SCRIPT_DEPLOY_DIR" ]]; then
        SCRIPT_DEPLOY_DIR="$ARM_CONFIG_DIR"
    fi
    DEPLOYED_SCRIPT="$SCRIPT_DEPLOY_DIR/notify_transcoder.sh"

    if [[ ! -f "$NOTIFY_TEMPLATE" ]]; then
        echo "ERROR: Template not found at $NOTIFY_TEMPLATE" >&2
        echo "       Run this script from the arm-transcoder repository." >&2
        exit 1
    fi

    # Copy and substitute values
    mkdir -p "$SCRIPT_DEPLOY_DIR"
    cp "$NOTIFY_TEMPLATE" "$DEPLOYED_SCRIPT"
    sed -i "s|TRANSCODER_URL=\".*\"|TRANSCODER_URL=\"${TRANSCODER_URL}\"|" "$DEPLOYED_SCRIPT"
    sed -i "s|WEBHOOK_SECRET=\".*\"|WEBHOOK_SECRET=\"${WEBHOOK_SECRET}\"|" "$DEPLOYED_SCRIPT"
    if [[ -n "$LOCAL_RAW_PATH" ]]; then
        sed -i "s|LOCAL_RAW_PATH=\".*\"|LOCAL_RAW_PATH=\"${LOCAL_RAW_PATH}\"|" "$DEPLOYED_SCRIPT"
        sed -i "s|NFS_RAW_PATH=\".*\"|NFS_RAW_PATH=\"${NFS_RAW_PATH}\"|" "$DEPLOYED_SCRIPT"
    fi
    chmod +x "$DEPLOYED_SCRIPT"

    echo "  Deployed: $DEPLOYED_SCRIPT"
    echo "  TRANSCODER_URL=$TRANSCODER_URL"
    echo "  WEBHOOK_SECRET=****${WEBHOOK_SECRET: -4}"
    if [[ -n "$LOCAL_RAW_PATH" ]]; then
        echo "  LOCAL_RAW_PATH=$LOCAL_RAW_PATH"
        echo "  NFS_RAW_PATH=$NFS_RAW_PATH"
    fi

    # Update arm.yaml: use BASH_SCRIPT, clear JSON_URL
    patch_yaml "BASH_SCRIPT" "\"${DEPLOYED_SCRIPT}\""
    patch_yaml "JSON_URL" '""'
    echo "  BASH_SCRIPT: \"$DEPLOYED_SCRIPT\""
    echo "  JSON_URL: \"\""
else
    # Simple mode: set JSON_URL, clear BASH_SCRIPT
    patch_yaml "JSON_URL" "\"${TRANSCODER_URL}\""
    patch_yaml "BASH_SCRIPT" '""'
    echo "  JSON_URL: \"$TRANSCODER_URL\""
    echo "  BASH_SCRIPT: \"\""
fi

# --- Restart ARM if requested ---
if [[ "$RESTART" == true ]]; then
    echo ""
    echo "Restarting ARM..."
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^arm"; then
        CONTAINER=$(docker ps --format '{{.Names}}' | grep "^arm" | head -1)
        docker restart "$CONTAINER"
        echo "  Restarted Docker container: $CONTAINER"
    elif systemctl is-active --quiet armui 2>/dev/null; then
        systemctl restart armui
        echo "  Restarted systemd service: armui"
    else
        echo "  WARNING: Could not find ARM Docker container or systemd service to restart."
        echo "           Please restart ARM manually."
    fi
fi

# --- Summary ---
echo ""
echo "=== Setup complete ==="
echo ""
echo "Test with:"
if [[ -n "$WEBHOOK_SECRET" ]]; then
    cat <<EOF
  curl -s -X POST ${TRANSCODER_URL} \\
    -H "Content-Type: application/json" \\
    -H "X-Webhook-Secret: ${WEBHOOK_SECRET}" \\
    -d '{"title": "ARM notification", "body": "Test Movie (2024) rip complete. Starting transcode.", "type": "info"}'
EOF
else
    cat <<EOF
  curl -s -X POST ${TRANSCODER_URL} \\
    -H "Content-Type: application/json" \\
    -d '{"title": "ARM notification", "body": "Test Movie (2024) rip complete. Starting transcode.", "type": "info"}'
EOF
fi
echo ""
