#!/usr/bin/env bash
# Stop FlowType starting at login (macOS / Linux)
rm -f "$HOME/Library/LaunchAgents/com.flowtype.app.plist" "$HOME/.config/autostart/flowtype.desktop"
echo "FlowType will no longer start at login."
