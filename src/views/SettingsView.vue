<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { invoke } from "@tauri-apps/api/core";
import { useMultiSpeaker } from "../composables/useMultiSpeaker";
import { useTestAdhan } from "../composables/useTestAdhan";

const router = useRouter();
const { multiSpeakerEnabled } = useMultiSpeaker();
const { isTesting, testAdhan } = useTestAdhan();

const devices = ref<string[]>([]);
const devicesError = ref<string | null>(null);

async function loadDevices() {
  devicesError.value = null;
  try {
    devices.value = await invoke<string[]>("list_audio_output_devices");
  } catch (e) {
    devices.value = [];
    devicesError.value = String(e);
  }
}

function goBack() {
  router.push("/");
}

onMounted(() => {
  void loadDevices();
});
</script>

<template>
  <main class="settings-page">
    <div class="settings-header">
      <button type="button" class="back-btn" @click="goBack">← رجوع</button>
      <h1>الإعدادات</h1>
    </div>

    <section class="settings-section">
      <label class="toggle-row">
        <span class="toggle-label">تشغيل الأذان على جميع مخرجات الصوت</span>
        <input v-model="multiSpeakerEnabled" type="checkbox" />
      </label>
      <p class="settings-hint">
        عند التفعيل، يُشغَّل الأذان في الوقت نفسه على كل مخرج صوت حقيقي (مثل سماعات الجهاز وBluetooth).
        تُستبعد تلقائياً منافذ HDMI والأسماء التقنية المكررة.
        ملاحظة: سماعات اللابتوب وسماعة الرأس السلكية غالباً مخرج واحد يتبدل تلقائياً.
        إذا فشل مخرج، تستمر المخرجات الأخرى.
      </p>
    </section>

    <section class="settings-section">
      <h2>مخرجات الصوت المتاحة</h2>
      <p v-if="devicesError" class="settings-error">
        تعذّر عرض الأجهزة: {{ devicesError }}
      </p>
      <ul v-else-if="devices.length" class="device-list">
        <li v-for="(name, i) in devices" :key="i">{{ name }}</li>
      </ul>
      <p v-else class="settings-hint">لا توجد مخرجات صوت مكتشفة.</p>
      <button type="button" class="secondary-btn" @click="loadDevices">
        تحديث القائمة
      </button>
    </section>

    <section class="settings-section">
      <button
        type="button"
        class="primary-btn"
        :disabled="isTesting"
        @click="testAdhan"
      >
        {{ isTesting ? "جاري التشغيل…" : "تجربة الأذان (الظهر)" }}
      </button>
    </section>
  </main>
</template>

<style scoped>
.settings-page {
  margin: 0;
  padding: 20px;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-family: "Arial", sans-serif;
}

.settings-header {
  margin-bottom: 24px;
}

.settings-header h1 {
  margin: 12px 0 0;
  font-size: 2rem;
  font-weight: 300;
  text-align: center;
}

.back-btn {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  border-radius: 8px;
  color: white;
  padding: 8px 14px;
  cursor: pointer;
  font-size: 1rem;
}

.back-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.settings-section {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 16px;
}

.settings-section h2 {
  margin: 0 0 12px;
  font-size: 1.2rem;
  font-weight: 400;
}

.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  cursor: pointer;
}

.toggle-label {
  flex: 1;
  font-size: 1.05rem;
}

.toggle-row input {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  cursor: pointer;
}

.settings-hint {
  margin: 12px 0 0;
  font-size: 0.9rem;
  opacity: 0.85;
  line-height: 1.5;
}

.settings-error {
  color: #ffcdd2;
  margin: 0 0 8px;
}

.device-list {
  margin: 0 0 12px;
  padding-inline-start: 20px;
}

.device-list li {
  margin-bottom: 6px;
}

.primary-btn,
.secondary-btn {
  border: none;
  border-radius: 10px;
  padding: 10px 18px;
  cursor: pointer;
  font-size: 1rem;
  color: white;
}

.primary-btn {
  background: rgba(76, 175, 80, 0.85);
  width: 100%;
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.secondary-btn {
  background: rgba(255, 255, 255, 0.2);
  margin-top: 8px;
}

.primary-btn:hover:not(:disabled),
.secondary-btn:hover {
  filter: brightness(1.1);
}
</style>
