#!/usr/bin/env bash
set -euo pipefail

APP_NAME="CyberDeck Music HUD"
INSTALL_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/music-hud"
SKIN_DIR="$CONFIG_DIR/skins"
SERVICE_DIR="$HOME/.config/systemd/user"

echo "Installing $APP_NAME..."

# Check required runtime commands before changing the system.
missing=()

for cmd in python3 cava mpc systemctl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing+=("$cmd")
    fi
done

if (( ${#missing[@]} > 0 )); then
    echo
    echo "Missing required commands: ${missing[*]}"
    echo
    echo "On Arch Linux / Omarchy, install the missing packages before"
    echo "running this installer again."
    exit 1
fi

# Check required Python GUI modules.
if ! python3 -c 'import gi, cairo; from gi.repository import Gtk, Gtk4LayerShell' >/dev/null 2>&1; then
    echo
    echo "Required Python GUI modules are missing:"
    echo "  PyGObject / GTK4 / Pycairo / Gtk4LayerShell"
    echo
    echo "On Arch Linux / Omarchy, install the required packages before"
    echo "running this installer again."
    exit 1
fi

# Make sure the installer is being run from the repository.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"
mkdir -p "$SKIN_DIR"
mkdir -p "$SERVICE_DIR"

echo "Installing application..."
install -m 755 "$SCRIPT_DIR/music-hud.py" "$INSTALL_DIR/music-hud.py"

echo "Installing skins..."
cp -f "$SCRIPT_DIR"/skins/*.json "$SKIN_DIR/"

if [[ ! -f "$SKIN_DIR/night-city-cyberdeck.png" ]]; then
    cp "$SCRIPT_DIR/assets/night-city-cyberdeck.png" "$SKIN_DIR/"
else
    echo "Keeping existing CyberDeck artwork."
fi

echo "Installing CAVA configuration..."
if [[ ! -f "$CONFIG_DIR/cava.conf" ]]; then
    cp "$SCRIPT_DIR/config/cava.conf" "$CONFIG_DIR/"
else
    echo "Keeping existing CAVA configuration."
fi

echo "Installing systemd service..."
install -m 644 "$SCRIPT_DIR/music-hud.service" \
    "$SERVICE_DIR/music-hud.service"

systemctl --user daemon-reload

echo
echo "Installation complete."
echo
echo "To enable the HUD at login:"
echo "  systemctl --user enable --now music-hud.service"
echo
echo "To check the service:"
echo "  systemctl --user status music-hud.service"
echo
echo "If your music is not in ~/Music, set:"
echo "  MUSIC_HUD_MUSIC_DIR=/path/to/your/music"
