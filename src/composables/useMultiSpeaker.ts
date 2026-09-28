import { ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";

const STORAGE_KEY = "multiSpeakerEnabled";

const multiSpeakerEnabled = ref(localStorage.getItem(STORAGE_KEY) === "1");

async function syncToRust(enabled: boolean) {
  try {
    await invoke("set_multi_speaker_enabled", { enabled });
  } catch (e) {
    console.warn("[multi-speaker] sync failed:", e);
  }
}

watch(multiSpeakerEnabled, (enabled) => {
  localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
  void syncToRust(enabled);
});

export function useMultiSpeaker() {
  void syncToRust(multiSpeakerEnabled.value);

  return { multiSpeakerEnabled };
}
