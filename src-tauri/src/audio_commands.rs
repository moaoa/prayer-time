use crate::audio_output::{list_output_device_names, AudioPreferences};
use tauri::State;

#[tauri::command]
pub fn set_multi_speaker_enabled(
    enabled: bool,
    prefs: State<'_, AudioPreferences>,
) -> Result<(), String> {
    let mut guard = prefs.0.lock().map_err(|e| e.to_string())?;
    guard.multi_speaker_enabled = enabled;
    Ok(())
}

#[tauri::command]
pub fn list_audio_output_devices() -> Result<Vec<String>, String> {
    list_output_device_names()
}

pub fn is_multi_speaker_enabled(prefs: &AudioPreferences) -> bool {
    prefs
        .0
        .lock()
        .map(|g| g.multi_speaker_enabled)
        .unwrap_or(false)
}
