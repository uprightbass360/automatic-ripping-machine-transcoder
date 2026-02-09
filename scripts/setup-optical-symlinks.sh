#!/usr/bin/env bash
# Stable Optical Drive Symlinks - Create persistent /dev/ symlinks for optical drives
#
# Linux assigns /dev/sr0, /dev/sr1, etc. based on kernel enumeration order,
# which can change between reboots or USB re-plugs. This script creates udev
# rules that assign stable symlinks (e.g. /dev/optical0) based on drive
# vendor/model identity, so Docker device mappings don't break.
#
# Usage:
#   setup-optical-symlinks.sh --list
#   setup-optical-symlinks.sh --auto [--prefix NAME]
#   setup-optical-symlinks.sh --device srN --symlink NAME
#   setup-optical-symlinks.sh --uninstall
#
# Examples:
#   # Show detected optical drives
#   ./setup-optical-symlinks.sh --list
#
#   # Auto-create /dev/optical0, /dev/optical1, ...
#   sudo ./setup-optical-symlinks.sh --auto
#
#   # Auto-create with custom prefix: /dev/bluray0, /dev/bluray1, ...
#   sudo ./setup-optical-symlinks.sh --auto --prefix bluray
#
#   # Manual: map sr1 to /dev/bluray0
#   sudo ./setup-optical-symlinks.sh --device sr1 --symlink bluray0
#
#   # Remove rules and reload udev
#   sudo ./setup-optical-symlinks.sh --uninstall

set -euo pipefail

# --- Installed file paths ---
RULES_FILE="/etc/udev/rules.d/99-optical-symlinks.rules"

# --- Defaults ---
ACTION=""
PREFIX="optical"
DEVICE=""
SYMLINK=""

# --- Usage ---
usage() {
    cat <<EOF
Usage: $(basename "$0") --list
       $(basename "$0") --auto [--prefix NAME]
       $(basename "$0") --device srN --symlink NAME
       $(basename "$0") --uninstall

Create stable udev symlinks for optical drives so device paths survive reboots.

Modes:
  --list                 Show detected optical drives (no root required)
  --auto                 Auto-create symlinks for all detected drives
  --device sr1           Manual mode: specify source device (use with --symlink)
  --symlink bluray0      Manual mode: specify symlink name (use with --device)
  --uninstall            Remove rules file and reload udev

Options:
  --prefix NAME          Symlink prefix for --auto mode (default: optical)
                         Creates /dev/optical0, /dev/optical1, etc.
  -h, --help             Show this help

Examples:
  # List drives
  ./$(basename "$0") --list

  # Auto-create /dev/optical0, /dev/optical1, ...
  sudo ./$(basename "$0") --auto

  # Auto-create with custom prefix
  sudo ./$(basename "$0") --auto --prefix bluray

  # Manual: map specific drive to specific name
  sudo ./$(basename "$0") --device sr1 --symlink bluray0

  # Clean up
  sudo ./$(basename "$0") --uninstall
EOF
    exit "${1:-0}"
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --list)
            ACTION="list"
            shift
            ;;
        --auto)
            ACTION="auto"
            shift
            ;;
        --device)
            ACTION="manual"
            DEVICE="$2"
            shift 2
            ;;
        --symlink)
            SYMLINK="$2"
            shift 2
            ;;
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --uninstall)
            ACTION="uninstall"
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

# --- Helpers ---

# Read and trim a sysfs attribute (SCSI fields are padded with spaces)
read_sysfs() {
    local path="$1"
    if [[ -f "$path" ]]; then
        sed 's/^[[:space:]]*//;s/[[:space:]]*$//' < "$path"
    fi
}

# Discover optical drives via sysfs
# Populates parallel arrays: DRIVES[], VENDORS[], MODELS[]
discover_drives() {
    DRIVES=()
    VENDORS=()
    MODELS=()

    for block_path in /sys/class/block/sr*; do
        [[ -d "$block_path" ]] || continue
        local dev_name
        dev_name="$(basename "$block_path")"
        local vendor model
        vendor="$(read_sysfs "$block_path/device/vendor")"
        model="$(read_sysfs "$block_path/device/model")"

        if [[ -n "$vendor" || -n "$model" ]]; then
            DRIVES+=("$dev_name")
            VENDORS+=("$vendor")
            MODELS+=("$model")
        fi
    done
}

# Generate a single udev rule line
make_rule() {
    local vendor="$1"
    local model="$2"
    local symlink_name="$3"

    echo "SUBSYSTEM==\"block\", KERNEL==\"sr*\", ATTRS{vendor}==\"${vendor}*\", ATTRS{model}==\"${model}*\", SYMLINK+=\"${symlink_name}\""
}

# --- Action: list ---
if [[ "$ACTION" == "list" ]]; then
    discover_drives

    if [[ ${#DRIVES[@]} -eq 0 ]]; then
        echo "No optical drives detected in /sys/class/block/sr*"
        exit 0
    fi

    echo "Detected optical drives:"
    echo ""
    for i in "${!DRIVES[@]}"; do
        echo "  /dev/${DRIVES[$i]}"
        echo "    Vendor: ${VENDORS[$i]}"
        echo "    Model:  ${MODELS[$i]}"
        echo ""
    done
    exit 0
fi

# --- Action: uninstall ---
if [[ "$ACTION" == "uninstall" ]]; then
    if [[ $EUID -ne 0 ]]; then
        echo "ERROR: This script must be run as root (sudo)" >&2
        exit 1
    fi

    echo "=== Uninstalling Optical Drive Symlinks ==="
    echo ""

    if [[ -f "$RULES_FILE" ]]; then
        rm -f "$RULES_FILE"
        echo "  Removed: $RULES_FILE"
        udevadm control --reload-rules
        udevadm trigger
        echo "  Reloaded udev rules."
    else
        echo "  Nothing to remove — no rules file found."
    fi

    echo ""
    echo "=== Uninstall complete ==="
    exit 0
fi

# --- Root check (auto and manual modes require root) ---
if [[ "$ACTION" == "auto" || "$ACTION" == "manual" ]]; then
    if [[ $EUID -ne 0 ]]; then
        echo "ERROR: This script must be run as root (sudo)" >&2
        exit 1
    fi
fi

# --- Action: auto ---
if [[ "$ACTION" == "auto" ]]; then
    # Validate prefix
    if [[ ! "$PREFIX" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ ]]; then
        echo "ERROR: --prefix must be alphanumeric (starting with a letter), got: $PREFIX" >&2
        exit 1
    fi

    discover_drives

    if [[ ${#DRIVES[@]} -eq 0 ]]; then
        echo "No optical drives detected in /sys/class/block/sr*"
        exit 1
    fi

    # Warn about duplicate vendor/model combinations
    declare -A seen_identity
    for i in "${!DRIVES[@]}"; do
        identity="${VENDORS[$i]}|${MODELS[$i]}"
        if [[ -n "${seen_identity[$identity]:-}" ]]; then
            echo "WARNING: /dev/${DRIVES[$i]} has the same vendor/model as /dev/${seen_identity[$identity]}"
            echo "         Identical drives cannot be distinguished by udev vendor/model rules alone."
            echo "         Consider using --device/--symlink mode with additional attributes."
            echo ""
        fi
        seen_identity["$identity"]="${DRIVES[$i]}"
    done

    echo "=== Creating Optical Drive Symlinks ==="
    echo ""

    # Generate rules file
    {
        echo "# Stable optical drive symlinks"
        echo "# Generated by setup-optical-symlinks.sh — do not edit manually"
        echo ""
        for i in "${!DRIVES[@]}"; do
            symlink_name="${PREFIX}${i}"
            echo "# /dev/${DRIVES[$i]} → /dev/${symlink_name}"
            make_rule "${VENDORS[$i]}" "${MODELS[$i]}" "$symlink_name"
        done
    } > "$RULES_FILE"

    echo "  Installed: $RULES_FILE"
    echo ""

    # Show rules
    echo "  Rules:"
    for i in "${!DRIVES[@]}"; do
        echo "    /dev/${DRIVES[$i]} (${VENDORS[$i]} ${MODELS[$i]}) → /dev/${PREFIX}${i}"
    done
    echo ""

    # Reload udev
    udevadm control --reload-rules
    udevadm trigger
    echo "  Reloaded udev rules."
    echo ""

    # Verify symlinks
    echo "  Verifying symlinks..."
    sleep 1
    all_ok=true
    for i in "${!DRIVES[@]}"; do
        symlink_name="${PREFIX}${i}"
        if [[ -L "/dev/${symlink_name}" ]]; then
            target="$(readlink -f "/dev/${symlink_name}")"
            echo "    /dev/${symlink_name} → ${target}  ✓"
        else
            echo "    /dev/${symlink_name}  ✗ (not yet created — may need a device replug or reboot)"
            all_ok=false
        fi
    done

    echo ""
    echo "=== Setup complete ==="
    echo ""
    if [[ "$all_ok" == true ]]; then
        echo "Use /dev/${PREFIX}0 in your Docker device mapping instead of /dev/${DRIVES[0]}."
    else
        echo "Some symlinks were not created yet. They will appear after a device"
        echo "replug or reboot. You can also trigger them with:"
        echo "  sudo udevadm trigger"
    fi
    echo ""
    echo "Uninstall:"
    echo "  sudo $(basename "$0") --uninstall"
    echo ""
    exit 0
fi

# --- Action: manual ---
if [[ "$ACTION" == "manual" ]]; then
    # Validate inputs
    if [[ -z "$DEVICE" ]]; then
        echo "ERROR: --device is required in manual mode" >&2
        usage 1
    fi
    if [[ -z "$SYMLINK" ]]; then
        echo "ERROR: --symlink is required with --device" >&2
        usage 1
    fi
    if [[ ! "$DEVICE" =~ ^sr[0-9]+$ ]]; then
        echo "ERROR: --device must match sr[0-9]+ (e.g. sr0, sr1), got: $DEVICE" >&2
        exit 1
    fi
    if [[ ! "$SYMLINK" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ ]]; then
        echo "ERROR: --symlink must be alphanumeric (starting with a letter), got: $SYMLINK" >&2
        exit 1
    fi

    # Read drive identity from sysfs
    block_path="/sys/class/block/$DEVICE"
    if [[ ! -d "$block_path" ]]; then
        echo "ERROR: /dev/$DEVICE not found (no sysfs entry at $block_path)" >&2
        exit 1
    fi

    vendor="$(read_sysfs "$block_path/device/vendor")"
    model="$(read_sysfs "$block_path/device/model")"

    if [[ -z "$vendor" && -z "$model" ]]; then
        echo "ERROR: Could not read vendor/model for /dev/$DEVICE" >&2
        exit 1
    fi

    echo "=== Creating Optical Drive Symlink ==="
    echo ""
    echo "  Device:  /dev/$DEVICE"
    echo "  Vendor:  $vendor"
    echo "  Model:   $model"
    echo "  Symlink: /dev/$SYMLINK"
    echo ""

    rule_line="$(make_rule "$vendor" "$model" "$SYMLINK")"

    # Append to existing rules file (or create), deduplicating by symlink name
    if [[ -f "$RULES_FILE" ]]; then
        # Remove any existing rule for this symlink name
        grep -v "SYMLINK+=\"${SYMLINK}\"" "$RULES_FILE" > "${RULES_FILE}.tmp" || true
        mv "${RULES_FILE}.tmp" "$RULES_FILE"
    else
        {
            echo "# Stable optical drive symlinks"
            echo "# Generated by setup-optical-symlinks.sh — do not edit manually"
            echo ""
        } > "$RULES_FILE"
    fi

    # Append the new rule
    {
        echo "# /dev/$DEVICE → /dev/$SYMLINK"
        echo "$rule_line"
    } >> "$RULES_FILE"

    echo "  Installed: $RULES_FILE"
    echo ""

    # Reload udev
    udevadm control --reload-rules
    udevadm trigger
    echo "  Reloaded udev rules."
    echo ""

    # Verify symlink
    echo "  Verifying..."
    sleep 1
    if [[ -L "/dev/${SYMLINK}" ]]; then
        target="$(readlink -f "/dev/${SYMLINK}")"
        echo "    /dev/${SYMLINK} → ${target}  ✓"
    else
        echo "    /dev/${SYMLINK}  ✗ (not yet created — may need a device replug or reboot)"
    fi

    echo ""
    echo "=== Setup complete ==="
    echo ""
    echo "Use /dev/${SYMLINK} in your Docker device mapping instead of /dev/${DEVICE}."
    echo ""
    echo "Uninstall:"
    echo "  sudo $(basename "$0") --uninstall"
    echo ""
    exit 0
fi

# --- No action specified ---
if [[ -z "$ACTION" ]]; then
    echo "ERROR: No action specified. Use --list, --auto, --device/--symlink, or --uninstall." >&2
    usage 1
fi
