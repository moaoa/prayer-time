use crate::audio_commands::is_multi_speaker_enabled;
use crate::audio_output::{play_sound, AudioPreferences};
use chrono::Local;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrayerAlarm {
    pub name: String,
    pub time_ms: i64,
    pub time_string: String,
}

#[derive(Default)]
pub struct SchedulerState {
    pub schedule: Vec<PrayerAlarm>,
    pub last_check_ms: i64,
    pub fired: HashSet<String>,
    pub day_key: String,
}

pub struct PrayerScheduler(pub Mutex<SchedulerState>);

const SOUND_WINDOW_MS: i64 = 5 * 60 * 1000;
const SOUND_GRACE_AFTER_MS: i64 = 60 * 1000;

fn should_play_sound(now_ms: i64, prayer_time_ms: i64) -> bool {
    now_ms >= prayer_time_ms - SOUND_WINDOW_MS && now_ms <= prayer_time_ms + SOUND_GRACE_AFTER_MS
}

#[derive(Clone, Serialize)]
struct PrayerAlarmPayload {
    prayer: String,
    time_string: String,
}

fn day_key_from_ms(ms: i64) -> String {
    if let Some(dt) = chrono::DateTime::from_timestamp_millis(ms) {
        dt.with_timezone(&Local).format("%Y-%m-%d").to_string()
    } else {
        Local::now().format("%Y-%m-%d").to_string()
    }
}

fn reset_day_if_needed(state: &mut SchedulerState, now_ms: i64) {
    let today = day_key_from_ms(now_ms);
    if state.day_key != today {
        state.day_key = today;
        state.fired.clear();
    }
}

fn resolve_sound_path(app: &AppHandle, prayer: &str) -> Option<PathBuf> {
    let extensions = ["mp3", "wav", "ogg", "m4a"];

    let manifest_sounds = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("sounds");
    for ext in extensions {
        let path = manifest_sounds.join(format!("{prayer}.{ext}"));
        if path.is_file() {
            return Some(path);
        }
    }

    for ext in extensions {
        let filename = format!("{prayer}.{ext}");
        if let Ok(path) = app.path().resolve(
            format!("sounds/{filename}"),
            tauri::path::BaseDirectory::Resource,
        ) {
            if path.is_file() {
                return Some(path);
            }
        }
    }

    None
}

fn trigger_alarm(app: &AppHandle, alarm: &PrayerAlarm, now_ms: i64) {
    if should_play_sound(now_ms, alarm.time_ms) {
        let prayer = alarm.name.clone();
        let app_for_audio = app.clone();
        let multi_speaker = app
            .try_state::<AudioPreferences>()
            .map(|p| is_multi_speaker_enabled(&p))
            .unwrap_or(false);

        std::thread::spawn(move || {
            if let Some(path) = resolve_sound_path(&app_for_audio, &prayer) {
                if let Err(e) = play_sound(&path, multi_speaker) {
                    eprintln!("[prayer-alarm] failed to play {}: {e}", path.display());
                }
            } else {
                eprintln!("[prayer-alarm] no sound file for prayer: {prayer}");
            }
        });
    }

    let _ = app.emit(
        "prayer-alarm",
        PrayerAlarmPayload {
            prayer: alarm.name.clone(),
            time_string: alarm.time_string.clone(),
        },
    );
}

pub fn run_scheduler_loop(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(1)).await;

            let now_ms = Local::now().timestamp_millis();
            let alarms_to_fire: Vec<PrayerAlarm> = {
                let state = app.state::<PrayerScheduler>();
                let mut guard = match state.0.lock() {
                    Ok(g) => g,
                    Err(_) => continue,
                };

                reset_day_if_needed(&mut guard, now_ms);

                let schedule = guard.schedule.clone();
                let day_key = guard.day_key.clone();
                let last_check_ms = guard.last_check_ms;
                let mut due = Vec::new();
                for alarm in &schedule {
                    if alarm.time_ms > last_check_ms && alarm.time_ms <= now_ms {
                        let key = format!("{}-{}", alarm.name, day_key);
                        if !guard.fired.contains(&key) {
                            guard.fired.insert(key);
                            due.push(alarm.clone());
                        }
                    }
                }

                guard.last_check_ms = now_ms;
                due
            };

            for alarm in alarms_to_fire {
                trigger_alarm(&app, &alarm, now_ms);
            }
        }
    });
}

#[tauri::command]
pub fn sync_prayer_schedule(
    schedule: Vec<PrayerAlarm>,
    state: State<'_, PrayerScheduler>,
) -> Result<(), String> {
    let now_ms = Local::now().timestamp_millis();
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    reset_day_if_needed(&mut guard, now_ms);
    guard.schedule = schedule;
    // Only initialize last_check on first sync so wake/focus catch-up still works.
    if guard.last_check_ms == 0 {
        guard.last_check_ms = now_ms;
    }
    Ok(())
}

#[tauri::command]
pub fn play_prayer_sound(
    prayer: String,
    app: AppHandle,
    prefs: State<'_, AudioPreferences>,
) -> Result<(), String> {
    let path = resolve_sound_path(&app, &prayer)
        .ok_or_else(|| format!("no sound file found for prayer: {prayer}"))?;
    let multi_speaker = is_multi_speaker_enabled(&prefs);
    std::thread::spawn(move || {
        if let Err(e) = play_sound(&path, multi_speaker) {
            eprintln!("[play_prayer_sound] {e}");
        }
    });
    Ok(())
}
