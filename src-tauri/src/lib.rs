mod audio_commands;
mod audio_output;
mod prayer_scheduler;

use audio_commands::{list_audio_output_devices, set_multi_speaker_enabled};
use audio_output::AudioPreferences;
use prayer_scheduler::{play_prayer_sound, sync_prayer_schedule, PrayerScheduler};
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::Builder::new().build())
        .plugin(tauri_plugin_os::init())
        .invoke_handler(tauri::generate_handler![
            sync_prayer_schedule,
            play_prayer_sound,
            set_multi_speaker_enabled,
            list_audio_output_devices
        ])
        .setup(|app| {
            app.manage(AudioPreferences(Default::default()));
            app.manage(PrayerScheduler(Default::default()));
            prayer_scheduler::run_scheduler_loop(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
