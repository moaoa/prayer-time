import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";

export function useTestAdhan(prayer = "dhuhr") {
  const isTesting = ref(false);

  async function testAdhan() {
    if (isTesting.value) return;
    isTesting.value = true;
    try {
      await invoke("play_prayer_sound", { prayer });
    } catch (e) {
      console.warn("[test-adhan] failed:", e);
    } finally {
      isTesting.value = false;
    }
  }

  return { isTesting, testAdhan };
}
