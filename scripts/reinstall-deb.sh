#!/usr/bin/env bash
# Rebuild (optional), gate on system linker, remove old packages, install .deb,
# retarget local overlay to /usr/bin, delete ~/.local/opt shadow copy.
#
# Run in a normal Ubuntu terminal (not Cursor's Nix/agent sandbox):
#   pnpm reinstall:deb
# Skip build if you already built:
#   SKIP_BUILD=1 pnpm reinstall:deb

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BIN="src-tauri/target/release/libya-prayer-time"
DEB_GLOB="src-tauri/target/release/bundle/deb/*.deb"

# Prefer Ubuntu gcc/ld over Nix wrappers on PATH (Cursor/.nix-profile).
# Without this, release binaries get interpreter /nix/store/.../ld-linux and fail on host.
use_system_toolchain() {
  if [[ -x /usr/bin/gcc ]]; then
    export CC=/usr/bin/gcc
    export CXX=/usr/bin/g++
    export AR=/usr/bin/ar
    export CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=/usr/bin/gcc
  fi
  # Put system bins first; drop nix profile bins from PATH for this process.
  local cleaned
  cleaned="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vE '/\.nix-profile/|/nix/var/nix/|/nix/store/' | paste -sd: -)"
  export PATH="/usr/bin:/bin:/usr/local/bin:${cleaned}"
  echo "==> Toolchain: CC=${CC:-unset} linker=$(command -v ld) cc=$(command -v cc)"
}

if [[ "${SKIP_BUILD:-}" != "1" ]]; then
  use_system_toolchain
  echo "==> Building release (.deb)…"
  # Force a full link with the system toolchain (object cache may be Nix-tainted).
  (cd src-tauri && cargo clean -p libya-prayer-time 2>/dev/null || cargo clean)
  pnpm tauri build
fi

if [[ ! -f "$BIN" ]]; then
  echo "ERROR: missing $BIN — build first (or unset SKIP_BUILD)."
  exit 1
fi

echo "==> Checking linker on $BIN"
file "$BIN"
if file "$BIN" | grep -q '/nix/store/'; then
  echo "ERROR: binary is still Nix-linked. Stop."
  echo "Hint: ensure /usr/bin/gcc is used (this script sets CC). Avoid building with Nix cc on PATH."
  exit 1
fi
if ! file "$BIN" | grep -Eq 'interpreter /lib(64)?/ld-linux-x86-64\.so\.2|/lib64/ld-linux-x86-64\.so\.2'; then
  echo "ERROR: expected system linker (ld-linux-x86-64.so.2). Stop."
  exit 1
fi

# Prefer the known product name; fall back to newest .deb in the bundle dir.
DEB="src-tauri/target/release/bundle/deb/Libya Prayer Times_0.1.0_amd64.deb"
if [[ ! -f "$DEB" ]]; then
  # shellcheck disable=SC2086
  DEB="$(ls -t $DEB_GLOB 2>/dev/null | head -1 || true)"
fi
if [[ -z "${DEB:-}" || ! -f "$DEB" ]]; then
  echo "ERROR: no .deb found under src-tauri/target/release/bundle/deb/"
  exit 1
fi
echo "==> Using package: $DEB"

echo "==> Stopping running instances…"
pkill -f libya-prayer-time || true
sleep 1

echo "==> Checking sudo (needed for dpkg)…"
if ! sudo -n true 2>/dev/null; then
  if [[ ! -t 0 ]]; then
    echo "ERROR: sudo needs a password, but this session has no terminal."
    echo "Build is OK (system-linked). Finish install in your own Ubuntu terminal:"
    echo "  cd $ROOT && pnpm reinstall:deb:only"
    exit 1
  fi
  echo "Enter your sudo password when prompted."
  sudo -v
fi

echo "==> Removing old packages (libya-prayer-times, prayer-time)…"
sudo dpkg --remove libya-prayer-times prayer-time || true
sudo dpkg --purge libya-prayer-times prayer-time || true

echo "==> Installing $DEB…"
sudo dpkg -i "$DEB"

echo "==> Retargeting ~/.local symlink + autostart…"
mkdir -p "${HOME}/.local/bin"
ln -sfn /usr/bin/libya-prayer-time "${HOME}/.local/bin/libya-prayer-time"

AUTOSTART="${HOME}/.config/autostart/Libya Prayer Times.desktop"
if [[ -f "$AUTOSTART" ]]; then
  sed -i 's|^Exec=.*|Exec=/usr/bin/libya-prayer-time|' "$AUTOSTART"
fi

echo "==> Removing local install overlay…"
rm -rf "${HOME}/.local/opt/libya-prayer-times"

echo "==> Sanity checks"
file /usr/bin/libya-prayer-time
readlink -f "${HOME}/.local/bin/libya-prayer-time"

if file /usr/bin/libya-prayer-time | grep -q '/nix/store/'; then
  echo "ERROR: installed /usr/bin/libya-prayer-time is still Nix-linked."
  exit 1
fi

echo "==> Launching /usr/bin/libya-prayer-time"
/usr/bin/libya-prayer-time >/dev/null 2>&1 &

echo "Done. Check Settings (PipeWire sink names) and Test adhan ON/OFF multi-speaker."
echo "Confirm exe: readlink -f /proc/\$(pgrep -n -f libya-prayer-time)/exe"
