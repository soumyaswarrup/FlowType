#!/usr/bin/env bash
# FlowType setup for macOS and Linux. Run:  bash setup.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
OS="$(uname)"
echo "=== FlowType setup ($OS) ==="

# 1. Python 3.10+ with Tk
PY=""
for c in python3.12 python3.13 python3.11 python3.10 python3.14 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ not found."
  [ "$OS" = "Darwin" ] && echo "  Install it with: brew install python@3.12 python-tk@3.12   (or from python.org)"
  [ "$OS" = "Linux" ] && echo "  Install it with: sudo apt install python3 python3-venv python3-tk"
  exit 1
fi
if ! "$PY" -c 'import tkinter' 2>/dev/null; then
  echo "Tkinter is missing for $PY."
  [ "$OS" = "Darwin" ] && echo "  Fix: brew install python-tk@3.12   (or use the python.org installer)"
  [ "$OS" = "Linux" ] && echo "  Fix: sudo apt install python3-tk"
  exit 1
fi
echo "Using $($PY --version)"

# 2. Linux system pieces (audio, clipboard, tray)
if [ "$OS" = "Linux" ]; then
  MISSING=""
  ldconfig -p 2>/dev/null | grep -q libportaudio || MISSING="$MISSING libportaudio2"
  command -v xclip >/dev/null || command -v xsel >/dev/null || command -v wl-copy >/dev/null || MISSING="$MISSING xclip"
  command -v xdotool >/dev/null || MISSING="$MISSING xdotool"
  if [ -n "$MISSING" ]; then
    echo "Installing:$MISSING (needs your password)"
    if command -v apt-get >/dev/null; then sudo apt-get install -y $MISSING
    elif command -v dnf >/dev/null; then sudo dnf install -y portaudio xclip xdotool
    elif command -v pacman >/dev/null; then sudo pacman -S --noconfirm portaudio xclip xdotool
    else echo "Please install:$MISSING with your package manager"; fi
  fi
  if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    echo "NOTE: you're on Wayland. Global hotkeys and typing work only in X11/XWayland apps."
    echo "      For full support, choose 'Ubuntu on Xorg' (or similar) on the login screen."
  fi
fi

# 3. Python packages + speech model
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
echo "Installing packages (2-5 minutes)..."
.venv/bin/python -m pip install -r requirements.txt
echo "Downloading the speech model (one time, ~500 MB)..."
.venv/bin/python flowtype.py --download-model

# 4. Start automatically at login
if [ "$OS" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/com.flowtype.app.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.flowtype.app</string>
  <key>ProgramArguments</key><array><string>$DIR/.venv/bin/python</string><string>$DIR/flowtype.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
</dict></plist>
PL
else
  mkdir -p "$HOME/.config/autostart" "$HOME/.local/share/applications"
  for f in "$HOME/.config/autostart/flowtype.desktop" "$HOME/.local/share/applications/flowtype.desktop"; do
    cat > "$f" <<DT
[Desktop Entry]
Type=Application
Name=FlowType
Comment=Talk instead of typing
Exec="$DIR/.venv/bin/python" "$DIR/flowtype.py"
Path=$DIR
Icon=$DIR/flowtype.ico
Terminal=false
X-GNOME-Autostart-enabled=true
DT
  done
fi

# 5. Start it
bash "$DIR/flowtype.sh"
echo
echo "=== Done! FlowType is running (mic icon in the menu bar / system tray). ==="
echo "Hold Ctrl+Option (Mac) / Ctrl+Alt (Linux), speak, release."
if [ "$OS" = "Darwin" ]; then
  echo
  echo "macOS will ask for permissions. In System Settings > Privacy & Security allow, for 'Python' / Terminal:"
  echo "  - Microphone   - Accessibility   - Input Monitoring"
  echo "Then quit FlowType from its menu-bar icon and run:  bash flowtype.sh"
fi
