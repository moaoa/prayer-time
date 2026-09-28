# Prayer Times (desktop app)

Domain language for the Libya Prayer Times Tauri app on Ubuntu: prayer alerts, sound outputs, and which binary actually runs.

## Language

**Adhan:**
The prayer call sound played at a scheduled prayer time (or via Test adhan).
_Avoid_: alarm (unless talking about the OS notification), track, clip

**PipeWire sink:**
One real playback target shown by the session (for example laptop Speaker + Headphones, or a Bluetooth headset).
_Avoid_: ALSA device, sound card, speaker name (when you mean the OS sink)

**ALSA alias:**
A low-level access name for the same sound chip (`hw:`, `plughw:`, `dmix:`, `default`, `pipewire` as a device string). Not a separate speaker.
_Avoid_: sink, device (when you mean a friendly output)

**Multi-speaker mode:**
App setting that plays the **Adhan** on every usable **PipeWire sink** at once.
_Avoid_: surround, all devices (when that includes ALSA aliases)

**System-linked binary:**
A built app whose ELF loader is the host Ubuntu linker (for example `/lib64/ld-linux-x86-64.so.2`).
_Avoid_: release build (alone — a release can still be Nix-linked)

**Nix-linked binary:**
A built app whose ELF loader points under `/nix/store/…`. Often fails on normal Ubuntu with missing libs such as `libasound.so.2`.
_Avoid_: broken install (say why: Nix-linked)

**Local install overlay:**
A user copy under `~/.local/opt/…` plus `~/.local/bin` and autostart that can run instead of `/usr/bin/libya-prayer-time`.
_Avoid_: the installed app (when you mean this shadow copy)

## Relationships

- An **Adhan** plays to one or more **PipeWire sinks** (one if multi-speaker is off; many if **Multi-speaker mode** is on)
- An **ALSA alias** is not a **PipeWire sink**
- A **Local install overlay** may shadow the package binary even when a **System-linked binary** is installed under `/usr/bin`
- A **Nix-linked binary** must not be treated as a successful update

## Example dialogue

> **Dev:** "I installed the new `.deb`. Why does Settings still show `hw:CARD=sofhdadsp`?"
> **Domain expert:** "Check which binary is running. If a **Local install overlay** is still active, you are on the old build. If `/usr/bin` is a **Nix-linked binary**, it may not start at all — rebuild a **System-linked binary** first. Only then trust the **PipeWire sink** list."

## Flagged ambiguities

- "device" was used for both **PipeWire sink** and **ALSA alias** — resolved: prefer those two terms; say "device" only in casual UI copy after filtering.
- "install" was used for both `dpkg -i` and copying into `~/.local/opt` — resolved: package install vs **Local install overlay**.
