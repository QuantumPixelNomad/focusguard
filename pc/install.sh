#!/bin/sh
# Install or upgrade FocusGuard. Run with: sudo ./install.sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run this with sudo: sudo ./install.sh" >&2
    exit 1
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/focusguard

if [ -S /run/focusguard/control.sock ] && command -v focusguardctl >/dev/null 2>&1; then
    if focusguardctl status 2>/dev/null | grep -q "Blocking is ON" && \
       focusguardctl status 2>/dev/null | grep -q "Strict mode: on"; then
        echo "A strict block is running. Upgrade after it ends." >&2
        exit 1
    fi
fi

echo "Installing required packages (Python 3, PyQt6 and python3-cryptography)..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y python3 python3-pyqt6 python3-cryptography e2fsprogs
else
    echo "apt-get not found: install Python 3 and PyQt6 for Python yourself." >&2
fi

echo "Copying files to $DEST..."
chattr -R -i "$DEST" 2>/dev/null || true
chattr -i /etc/systemd/system/focusguard.service /etc/systemd/system/focusguard-watchdog.service \
    /etc/systemd/system/focusguard-watchdog.timer 2>/dev/null || true
rm -rf "$DEST/focusguard" "$DEST/extension"
mkdir -p "$DEST" /etc/focusguard
chmod 700 /etc/focusguard
cp -r "$SRC/focusguard" "$DEST/focusguard"
find "$DEST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
python3 "$SRC/extension/build.py" "$DEST/extension" >/dev/null
cp "$SRC/uninstall.sh" "$DEST/uninstall.sh"
chown -R root:root "$DEST"
chmod -R go-w "$DEST"

cat > /usr/local/bin/focusguard <<'WRAP'
#!/bin/sh
PYTHONPATH=/opt/focusguard PYTHONDONTWRITEBYTECODE=1 exec /usr/bin/python3 -m focusguard.gui "$@"
WRAP
cat > /usr/local/bin/focusguardctl <<'WRAP'
#!/bin/sh
PYTHONPATH=/opt/focusguard PYTHONDONTWRITEBYTECODE=1 exec /usr/bin/python3 -m focusguard.cli "$@"
WRAP
chmod 755 /usr/local/bin/focusguard /usr/local/bin/focusguardctl

install -m 644 "$SRC/systemd/focusguard.service" "$SRC/systemd/focusguard-watchdog.service" \
    "$SRC/systemd/focusguard-watchdog.timer" /etc/systemd/system/
install -m 644 "$SRC/desktop/focusguard.desktop" /usr/share/applications/focusguard.desktop
install -m 644 "$SRC/desktop/focusguard-tray.desktop" /etc/xdg/autostart/focusguard-tray.desktop

systemctl daemon-reload
systemctl enable focusguard.service focusguard-watchdog.timer
systemctl restart focusguard.service
systemctl start focusguard-watchdog.timer

echo
echo "FocusGuard is installed and running."
echo "  Open it from the application menu, or run: focusguard"
echo "  Browser extension files: $DEST/extension (see README.md for how to add it)"
