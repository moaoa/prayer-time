use rodio::cpal::traits::{DeviceTrait, HostTrait};
use rodio::{cpal, Decoder, Device, OutputStream, Sink};
use serde_json::Value;
use std::fs::File;
use std::io::BufReader;
use std::path::Path;
use std::process::Command;
use std::sync::Mutex;
use std::thread;

pub struct AudioPreferences(pub Mutex<AudioPrefs>);

#[derive(Default)]
pub struct AudioPrefs {
    pub multi_speaker_enabled: bool,
}

/// A real playback sink as seen by PipeWire (friendly description + target name).
#[derive(Clone, Debug, PartialEq, Eq)]
struct OutputSink {
    /// Stable PipeWire node name, used with `pw-play --target`.
    target: String,
    /// Human-readable label for the UI (e.g. "soundcore R60i NC").
    description: String,
}

pub fn list_output_device_names() -> Result<Vec<String>, String> {
    match list_pipewire_sinks() {
        Ok(sinks) if !sinks.is_empty() => {
            return Ok(sinks.into_iter().map(|s| s.description).collect());
        }
        Ok(_) => {
            eprintln!("[audio] pw-dump returned no usable Audio/Sink nodes");
        }
        Err(e) => {
            eprintln!("[audio] PipeWire sink list failed: {e}");
        }
    }

    // Filtered CPAL only — never return raw ALSA aliases (hw:/plughw:/dmix:…).
    let names = list_cpal_output_device_names()?;
    if names.is_empty() {
        return Err(
            "No usable audio outputs found. Is PipeWire running? (pw-dump /usr/bin/pw-dump)"
                .into(),
        );
    }
    Ok(names)
}

fn list_cpal_output_device_names() -> Result<Vec<String>, String> {
    let host = cpal::default_host();
    let devices = host
        .output_devices()
        .map_err(|e| format!("enumerate output devices: {e}"))?;

    let mut names = Vec::new();
    for device in devices {
        let name = device
            .name()
            .unwrap_or_else(|_| "Unknown device".to_string());
        if is_usable_output(&name) {
            names.push(name);
        }
    }
    Ok(names)
}

/// Absolute paths so GUI/autostart launches with a thin PATH still work.
const PW_DUMP: &str = "/usr/bin/pw-dump";
const PW_PLAY: &str = "/usr/bin/pw-play";

/// PipeWire Audio/Sink nodes with friendly names (excludes HDMI, monitors, etc.).
fn list_pipewire_sinks() -> Result<Vec<OutputSink>, String> {
    let output = Command::new(PW_DUMP)
        .output()
        .map_err(|e| format!("{PW_DUMP}: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "{PW_DUMP} exited with {}",
            output.status.code().unwrap_or(-1)
        ));
    }

    let dump: Value =
        serde_json::from_slice(&output.stdout).map_err(|e| format!("parse pw-dump: {e}"))?;
    Ok(sinks_from_pw_dump(&dump))
}

fn sinks_from_pw_dump(dump: &Value) -> Vec<OutputSink> {
    let Some(objects) = dump.as_array() else {
        return Vec::new();
    };

    let mut sinks = Vec::new();
    for obj in objects {
        let props = match obj.pointer("/info/props") {
            Some(p) => p,
            None => continue,
        };
        if props.get("media.class").and_then(|v| v.as_str()) != Some("Audio/Sink") {
            continue;
        }
        let target = props
            .get("node.name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if target.is_empty() {
            continue;
        }
        let description = props
            .get("node.description")
            .and_then(|v| v.as_str())
            .or_else(|| props.get("node.nick").and_then(|v| v.as_str()))
            .unwrap_or(&target)
            .to_string();

        if is_hdmi_output(&description) || is_hdmi_output(&target) {
            continue;
        }
        if !is_usable_output(&description) {
            continue;
        }

        sinks.push(OutputSink {
            target,
            description,
        });
    }
    sinks
}

/// Skip virtual / unusable sinks that would duplicate or fail playback.
fn is_usable_output(name: &str) -> bool {
    let n = name.to_ascii_lowercase();
    !n.contains("monitor")
        && !n.contains("loopback")
        && !n.contains("null")
        && !n.contains("dummy")
        && !n.starts_with("hw:")
        && !n.starts_with("plughw:")
        && !n.starts_with("dmix:")
        && !n.starts_with("sysdefault:")
        && !n.starts_with("front:")
        && !n.starts_with("surround")
        && !n.starts_with("iec958:")
        && !n.starts_with("hdmi:")
        && !n.starts_with("phonon")
        && n != "pipewire"
        && n != "default"
        && n != "pulse"
}

fn is_hdmi_output(name: &str) -> bool {
    let n = name.to_ascii_lowercase();
    n.contains("hdmi") || n.contains("displayport") || n.contains("display port")
}

fn play_on_pipewire_sink(path: &Path, target: &str) -> Result<(), String> {
    let status = Command::new(PW_PLAY)
        .args(["--target", target])
        .arg(path)
        .status()
        .map_err(|e| format!("{PW_PLAY}: {e}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "{PW_PLAY} --target {target} failed (exit {})",
            status.code().unwrap_or(-1)
        ))
    }
}

fn collect_output_devices() -> Result<Vec<Device>, String> {
    let host = cpal::default_host();
    let devices = host
        .output_devices()
        .map_err(|e| format!("enumerate output devices: {e}"))?;

    Ok(devices
        .filter(|d| {
            d.name()
                .map(|n| is_usable_output(&n))
                .unwrap_or(false)
        })
        .map(|d| d.into())
        .collect())
}

pub fn play_sound_on_device(path: &Path, device: &Device) -> Result<(), String> {
    let (_stream, stream_handle) =
        OutputStream::try_from_device(device).map_err(|e| format!("audio output: {e}"))?;
    let sink = Sink::try_new(&stream_handle).map_err(|e| format!("audio sink: {e}"))?;
    let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    let source = Decoder::new(BufReader::new(file)).map_err(|e| format!("decode: {e}"))?;
    sink.append(source);
    sink.sleep_until_end();
    Ok(())
}

pub fn play_sound_default(path: &Path) -> Result<(), String> {
    let (_stream, stream_handle) =
        OutputStream::try_default().map_err(|e| format!("audio output: {e}"))?;
    let sink = Sink::try_new(&stream_handle).map_err(|e| format!("audio sink: {e}"))?;
    let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    let source = Decoder::new(BufReader::new(file)).map_err(|e| format!("decode: {e}"))?;
    sink.append(source);
    sink.sleep_until_end();
    Ok(())
}

pub fn play_sound(path: &Path, multi_speaker: bool) -> Result<(), String> {
    if !multi_speaker {
        return play_sound_default(path);
    }

    // Prefer PipeWire sinks so multi-speaker hits real devices (e.g. laptop + Bluetooth),
    // not dozens of ALSA aliases for the same card.
    match list_pipewire_sinks() {
        Ok(sinks) if !sinks.is_empty() => {
            return play_sound_on_pipewire_sinks(path, &sinks);
        }
        Ok(_) => {
            eprintln!("[multi-speaker] pw-dump returned no usable sinks; falling back");
        }
        Err(e) => {
            eprintln!("[multi-speaker] PipeWire list failed: {e}; falling back");
        }
    }

    let devices = collect_output_devices()?;
    if devices.is_empty() {
        return play_sound_default(path);
    }

    if devices.len() == 1 {
        return play_sound_on_device(path, &devices[0]);
    }

    let path = path.to_path_buf();
    let handles: Vec<_> = devices
        .into_iter()
        .map(|device| {
            let path = path.clone();
            thread::spawn(move || {
                let name = device.name().unwrap_or_else(|_| "unknown".to_string());
                if let Err(e) = play_sound_on_device(&path, &device) {
                    eprintln!("[multi-speaker] device \"{name}\": {e}");
                }
            })
        })
        .collect();

    for handle in handles {
        let _ = handle.join();
    }

    Ok(())
}

fn play_sound_on_pipewire_sinks(path: &Path, sinks: &[OutputSink]) -> Result<(), String> {
    if sinks.len() == 1 {
        return play_on_pipewire_sink(path, &sinks[0].target);
    }

    let path = path.to_path_buf();
    let handles: Vec<_> = sinks
        .iter()
        .cloned()
        .map(|sink| {
            let path = path.clone();
            thread::spawn(move || {
                if let Err(e) = play_on_pipewire_sink(&path, &sink.target) {
                    eprintln!(
                        "[multi-speaker] sink \"{}\" ({}): {e}",
                        sink.description, sink.target
                    );
                }
            })
        })
        .collect();

    for handle in handles {
        let _ = handle.join();
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn list_devices_does_not_panic() {
        let _ = list_output_device_names();
    }

    #[test]
    fn is_usable_output_rejects_virtual_and_alsa_aliases() {
        assert!(!is_usable_output("Monitor of Built-in Audio Analog Stereo"));
        assert!(!is_usable_output("monitor of default"));
        assert!(!is_usable_output("Loopback PCM"));
        assert!(!is_usable_output("Null Output"));
        assert!(!is_usable_output("Dummy Output"));
        assert!(!is_usable_output("hw:CARD=sofhdadsp,DEV=0"));
        assert!(!is_usable_output("plughw:CARD=sofhdadsp,DEV=3"));
        assert!(!is_usable_output("dmix:CARD=sofhdadsp,DEV=0"));
        assert!(!is_usable_output("sysdefault:CARD=sofhdadsp"));
        assert!(!is_usable_output("pipewire"));
        assert!(!is_usable_output("default"));
    }

    #[test]
    fn is_usable_output_keeps_real_devices() {
        assert!(is_usable_output("Built-in Audio Analog Stereo"));
        assert!(is_usable_output("Raptor Lake-P/U/H cAVS Speaker + Headphones"));
        assert!(is_usable_output("USB Audio Device"));
        assert!(is_usable_output("soundcore R60i NC"));
        assert!(is_usable_output("Bluetooth Headset"));
    }

    #[test]
    fn is_hdmi_output_detects_display_sinks() {
        assert!(is_hdmi_output(
            "Raptor Lake-P/U/H cAVS HDMI / DisplayPort 1 Output"
        ));
        assert!(is_hdmi_output("HDMI Audio"));
        assert!(!is_hdmi_output("Speaker + Headphones"));
        assert!(!is_hdmi_output("soundcore R60i NC"));
    }

    #[test]
    fn sinks_from_pw_dump_keeps_real_speakers_drops_hdmi() {
        let dump = serde_json::json!([
          {
            "id": 54,
            "info": {
              "props": {
                "media.class": "Audio/Sink",
                "node.name": "alsa_output.built-in",
                "node.description": "Speaker + Headphones"
              }
            }
          },
          {
            "id": 51,
            "info": {
              "props": {
                "media.class": "Audio/Sink",
                "node.name": "alsa_output.hdmi",
                "node.description": "HDMI / DisplayPort 1 Output"
              }
            }
          },
          {
            "id": 85,
            "info": {
              "props": {
                "media.class": "Audio/Sink",
                "node.name": "bluez_output.headset",
                "node.description": "soundcore R60i NC"
              }
            }
          },
          {
            "id": 99,
            "info": {
              "props": {
                "media.class": "Audio/Source",
                "node.name": "alsa_input.mic",
                "node.description": "Microphone"
              }
            }
          }
        ]);

        let sinks = sinks_from_pw_dump(&dump);
        assert_eq!(
            sinks
                .iter()
                .map(|s| s.description.as_str())
                .collect::<Vec<_>>(),
            vec!["Speaker + Headphones", "soundcore R60i NC"]
        );
    }
}
