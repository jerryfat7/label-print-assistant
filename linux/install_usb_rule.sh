#!/usr/bin/env bash
# Give one service user persistent access to DeTong P1 only. Run via sudo.
set -euo pipefail
service_user="${SUDO_USER:-}"
dry_run=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) [[ $# -ge 2 ]] || exit 2; service_user="$2"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    *) echo 'Usage: install_usb_rule.sh --user SERVICE_USER [--dry-run]'; exit 2 ;;
  esac
done
[[ -n "$service_user" ]] || { echo 'Specify the non-root service account with --user'; exit 2; }
service_uid="$(id -u -- "$service_user")"
[[ "$service_uid" != 0 ]] || { echo 'Select the non-root account running the print service'; exit 2; }
rule="SUBSYSTEM==\"usb\", ENV{DEVTYPE}==\"usb_device\", ATTR{idVendor}==\"3533\", ATTR{idProduct}==\"5a11\", OWNER:=\"$service_uid\", MODE:=\"0660\""
if "$dry_run"; then printf '%s\n' "$rule"; exit 0; fi
[[ "$EUID" == 0 ]] || { echo 'Run this installer with sudo; normal service operation does not need sudo'; exit 1; }
command -v udevadm >/dev/null
target=/etc/udev/rules.d/99-label-print-assistant-p1.rules
mkdir -p -- /etc/udev/rules.d
if [[ -e "$target" ]] && ! grep -Fxq -- "$rule" "$target"; then
  cp -p -- "$target" "$target.bak.$(date +%Y%m%d%H%M%S)"
fi
temporary="$(mktemp)"
trap 'rm -f -- "$temporary"' EXIT
printf '# DeTong P1 USB access for the configured service UID\n%s\n' "$rule" >"$temporary"
install -o root -g root -m 0644 -- "$temporary" "$target"
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=usb --attr-match=idVendor=3533 --attr-match=idProduct=5a11
udevadm settle --timeout=10
echo "Installed: $target"
echo 'The rule follows P1 vendor/product IDs across USB ports. Verify access after unplug/replug.'
