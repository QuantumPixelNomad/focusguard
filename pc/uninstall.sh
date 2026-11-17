#!/bin/sh
# Remove FocusGuard. Run with: sudo ./uninstall.sh
# The service must agree first: it asks for the password and refuses during a strict block.
set -eu

main() {

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run this with sudo." >&2
    exit 1
fi

if systemctl is-active --quiet focusguard.service 2>/dev/null; then
    focusguardctl prepare-uninstall || {
        echo "FocusGuard did not allow the uninstall." >&2
        exit 1
    }
fi
if [ ! -f /run/focusguard/uninstall-ok ] && systemctl is-active --quiet focusguard.service 2>/dev/null; then
    echo "FocusGuard did not allow the uninstall." >&2
    exit 1
fi

systemctl disable --now focusguard-watchdog.timer focusguard.service 2>/dev/null || true
chattr -R -i /opt/focusguard 2>/dev/null || true
for unit in focusguard.service focusguard-watchdog.service focusguard-watchdog.timer; do
    chattr -i "/etc/systemd/system/$unit" 2>/dev/null || true
    rm -f "/etc/systemd/system/$unit"
done
systemctl daemon-reload

# Take our section out of the hosts file, in case the service was not running.
if grep -q "FocusGuard" /etc/hosts 2>/dev/null; then
    sed -i '/^# >>> FocusGuard/,/^# <<< FocusGuard/d' /etc/hosts
fi
for d in /etc/opt/chrome/policies/managed /etc/chromium/policies/managed \
         /etc/chromium-browser/policies/managed /etc/brave/policies/managed /etc/opt/edge/policies/managed; do
    rm -f "$d/focusguard.json"
done

rm -f /usr/local/bin/focusguard /usr/local/bin/focusguardctl
rm -f /usr/share/applications/focusguard.desktop /etc/xdg/autostart/focusguard-tray.desktop
rm -rf /opt/focusguard /run/focusguard
if [ "${1:-}" = "--purge" ]; then
    rm -rf /etc/focusguard
    echo "FocusGuard and its settings were removed."
else
    echo "FocusGuard was removed. Settings are kept in /etc/focusguard (use --purge to delete them)."
fi
}

# Wrapped in a function so the script survives deleting its own copy in /opt/focusguard.
main "$@"
