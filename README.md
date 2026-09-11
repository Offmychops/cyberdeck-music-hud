# CyberDeck Music HUD

A cyberpunk-style music HUD for Linux desktops.

CyberDeck Music HUD displays your currently playing MPD track as a futuristic heads-up display, with album artwork, playback controls, progress, and a live CAVA audio visualizer.

Built with:

- Python
- GTK4
- Cairo
- gtk4-layer-shell
- MPD
- CAVA

Designed for Linux desktops, with Omarchy/Arch Linux as the primary environment.

## Features

- 🎵 MPD now-playing information
- 🖼️ Album artwork
- ▶️ Play / pause
- ⏮️ Previous track
- ⏭️ Next track
- 📊 Track progress
- 🎚️ Live CAVA visualizer
- 🖥️ Layer-shell desktop overlay
- 🎨 JSON-based skins
- ⚡ Cyberpunk animated hover/electrical effects
- 🔄 Automatic restart through systemd
- 🖥️ HiDPI-aware rendering

## Screenshots

The included `night-city-cyberdeck` skin provides the default CyberDeck appearance.

## Requirements

- Linux
- Python 3
- GTK4
- PyGObject
- Pycairo
- gtk4-layer-shell
- MPD
- CAVA

## Installation

Clone the repository:

    git clone https://github.com/YOUR_USERNAME/cyberdeck-music-hud.git
    cd cyberdeck-music-hud

Copy the application:

    mkdir -p ~/.local/bin
    cp music-hud.py ~/.local/bin/
    chmod +x ~/.local/bin/music-hud.py

Install the configuration:

    mkdir -p ~/.config/music-hud/skins

    cp config/cava.conf ~/.config/music-hud/
    cp skins/*.json ~/.config/music-hud/skins/
    cp assets/night-city-cyberdeck.png ~/.config/music-hud/skins/

Install the systemd service:

    mkdir -p ~/.config/systemd/user
    cp music-hud.service ~/.config/systemd/user/

Reload systemd:

    systemctl --user daemon-reload

Enable the HUD:

    systemctl --user enable --now music-hud.service

## Configuration

### Music directory

By default, the HUD looks for music in:

    ~/Music

You can override this with the `MUSIC_HUD_MUSIC_DIR` environment variable:

    export MUSIC_HUD_MUSIC_DIR="$HOME/Music"

For example:

    export MUSIC_HUD_MUSIC_DIR="/mnt/storage/Music"

For a persistent setting, add the variable to your shell environment before starting the HUD.

### Skins

Skins are stored as JSON files in:

    ~/.config/music-hud/skins/

The active skin is selected using:

    ~/.config/music-hud/active-skin

Each skin can specify its own artwork using the `skin_png` field. The corresponding PNG should be stored alongside the skin JSON in:

    ~/.config/music-hud/skins/


Skins are stored as JSON files in:

    ~/.config/music-hud/skins/

The active skin is selected using:

    ~/.config/music-hud/active-skin

## MPD

The HUD expects a working MPD installation and an accessible MPD music library.

Test MPD with:

    mpc status

## CAVA

CAVA provides the live audio visualizer.

Test CAVA with:

    cava -p ~/.config/music-hud/cava.conf

## Development

Run the HUD manually while developing:

    python3 ~/.local/bin/music-hud.py

Running it manually makes debugging easier than using systemd.

## Contributing

Pull requests, new skins, improvements and bug fixes are welcome.

If you create a new skin, please include the corresponding JSON configuration and any required artwork.

## License

The application code is released under the MIT License.

See `LICENSE`.

The included artwork may be subject to separate terms. Please see `ASSETS.md`.
