<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { enable } from "@tauri-apps/plugin-autostart";

// Declare Tauri global type
declare global {
  interface Window {
    __TAURI_INTERNALS__?: any;
  }
}

interface PrayerTimings {
  Fajr: string;
  Sunrise: string;
  Duhur: string;
  Asr: string;
  Maqhrib: string;
  Isha: string;
}

interface PrayerResponse {
  timings: PrayerTimings;
  meta: {
    countryAR: string;
    countryEN: string;
    cityAR: string;
    cityEN: string;
    timezone: string;
    lat: string;
    long: string;
    zone: number;
    ARdayName: string;
    ENdayName: string;
    HIJRIdate: string;
    GEOIdate: string;
    TimeNow: string;
    TimeNow24: string;
    timeStamp: number;
  };
}

const prayerData = ref<PrayerResponse | null>(null);
const currentTime = ref(new Date());
const loading = ref(true);
const error = ref<string>("");
const isCompactMode = ref(false);
const notificationShown = ref<string>("");
const isManualToggle = ref(false); // Track if user manually toggled
const showNextPrayer = ref(true); // true = show next prayer, false = show previous prayer

let timeInterval: number | null = null;

// Prayer names in order
const prayerOrder = ["Fajr", "Sunrise", "Duhur", "Asr", "Maqhrib", "Isha"];

// Function to fetch prayer times from API
async function fetchPrayerTimes() {
  try {
    loading.value = true;
    error.value = "";

    const apiUrl = import.meta.env.VITE_PRAYER_API_URL;
    if (!apiUrl) {
      throw new Error("API URL not found in environment variables");
    }

    console.log("Fetching from:", apiUrl);
    console.log("Tauri internals available:", !!window.__TAURI_INTERNALS__);

    let response;

    // Check if we're in Tauri environment
    if (window.__TAURI_INTERNALS__) {
      // Use Tauri's HTTP client for CORS-free requests (production)
      console.log("Using Tauri HTTP client");
      const { fetch: tauriFetch } = await import("@tauri-apps/plugin-http");
      response = await tauriFetch(apiUrl, {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
      });
      console.log("Tauri response status:", response.status);
    } else {
      // Fallback to regular fetch (development with proxy)
      console.log("Using regular fetch with proxy");
      const devApiUrl = apiUrl.includes("api.pray-times.com")
        ? "/api/prayer?country=libya&city=tripoli"
        : apiUrl;
      console.log("Dev API URL:", devApiUrl);
      response = await fetch(devApiUrl);
      console.log("Dev response status:", response.status);
    }

    if (!response.ok) {
      throw new Error(
        `HTTP error! status: ${response.status} - ${response.statusText}`
      );
    }

    const data: PrayerResponse = await response.json();
    prayerData.value = data;
    console.log("Prayer times fetched successfully:", data);
  } catch (err) {
    console.error("Detailed error:", err);
    error.value =
      err instanceof Error ? err.message : "Failed to fetch prayer times";
    console.error("Error fetching prayer times:", err);
  } finally {
    loading.value = false;
  }
}

// Convert prayer time string to Date object for today
function prayerTimeToDate(timeStr: string): Date {
  const [hours, minutes] = timeStr.split(":").map(Number);
  const date = new Date();
  date.setHours(hours, minutes, 0, 0);
  return date;
}

// Get next prayer
const nextPrayer = computed(() => {
  if (!prayerData.value) return null;

  const now = currentTime.value;

  for (const prayer of prayerOrder) {
    const prayerTime = prayerTimeToDate(
      prayerData.value.timings[prayer as keyof PrayerTimings]
    );

    if (prayerTime > now) {
      return {
        name: prayer,
        time: prayerTime,
        timeString: prayerData.value.timings[prayer as keyof PrayerTimings],
      };
    }
  }

  // If no prayer today, return first prayer of tomorrow
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const fajrTime = prayerTimeToDate(prayerData.value.timings.Fajr);
  fajrTime.setDate(tomorrow.getDate());

  return {
    name: "Fajr",
    time: fajrTime,
    timeString: prayerData.value.timings.Fajr,
  };
});

// Get previous prayer
const previousPrayer = computed(() => {
  if (!prayerData.value) return null;

  const now = currentTime.value;
  let lastPrayer = null;

  for (const prayer of prayerOrder) {
    const prayerTime = prayerTimeToDate(
      prayerData.value.timings[prayer as keyof PrayerTimings]
    );

    if (prayerTime <= now) {
      lastPrayer = {
        name: prayer,
        time: prayerTime,
        timeString: prayerData.value.timings[prayer as keyof PrayerTimings],
      };
    } else {
      break;
    }
  }

  // If no prayer passed today, get last prayer from yesterday
  if (!lastPrayer) {
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const ishaTime = prayerTimeToDate(prayerData.value.timings.Isha);
    ishaTime.setDate(yesterday.getDate());

    return {
      name: "Isha",
      time: ishaTime,
      timeString: prayerData.value.timings.Isha,
    };
  }

  return lastPrayer;
});

// Time remaining until next prayer
const timeRemaining = computed(() => {
  if (!nextPrayer.value) return null;

  const diff = nextPrayer.value.time.getTime() - currentTime.value.getTime();
  if (diff < 0) return null;

  const hours = Math.floor(diff / (1000 * 60 * 60));
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
  const seconds = Math.floor((diff % (1000 * 60)) / 1000);

  return { hours, minutes, seconds, totalMs: diff };
});

// Time passed since previous prayer
const timePassed = computed(() => {
  if (!previousPrayer.value) return null;

  const diff =
    currentTime.value.getTime() - previousPrayer.value.time.getTime();
  if (diff < 0) return null;

  const hours = Math.floor(diff / (1000 * 60 * 60));
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
  const seconds = Math.floor((diff % (1000 * 60)) / 1000);

  return { hours, minutes, seconds, totalMs: diff };
});

// Determine which mode to show (35 minutes threshold)
const shouldShowNextPrayer = computed(() => {
  if (isManualToggle.value) {
    return showNextPrayer.value;
  }

  if (!timePassed.value) return true;

  const thirtyFiveMinutesMs = 35 * 60 * 1000;
  return timePassed.value.totalMs > thirtyFiveMinutesMs;
});

// Current active prayer info (either next or previous based on mode)
const activePrayer = computed(() => {
  if (shouldShowNextPrayer.value) {
    return nextPrayer.value;
  } else {
    return previousPrayer.value;
  }
});

// Current time display (either remaining or passed)
const activeTimeDisplay = computed(() => {
  if (shouldShowNextPrayer.value) {
    return timeRemaining.value;
  } else {
    return timePassed.value;
  }
});

// Toggle between next and previous prayer manually
function togglePrayerMode() {
  isManualToggle.value = true;
  showNextPrayer.value = !showNextPrayer.value;
}

// Reset to automatic mode after some time
// function resetToAutoMode() {
//   setTimeout(() => {
//     isManualToggle.value = false;
//   }, 60000); // Reset after 1 minute
// }

// Show notification when prayer is close (5 minutes before)
function checkNotification() {
  if (!timeRemaining.value || !nextPrayer.value) return;

  const fiveMinutesMs = 5 * 60 * 1000;
  const oneMinuteMs = 1 * 60 * 1000;

  const prayerKey = nextPrayer.value.name;

  if (
    timeRemaining.value.totalMs <= fiveMinutesMs &&
    timeRemaining.value.totalMs > oneMinuteMs
  ) {
    if (notificationShown.value !== `${prayerKey}-5min`) {
      showNotification(
        `${nextPrayer.value.name} prayer in 5 minutes!`,
        `Time: ${nextPrayer.value.timeString}`
      );
      notificationShown.value = `${prayerKey}-5min`;
    }
  } else if (
    timeRemaining.value.totalMs <= oneMinuteMs &&
    timeRemaining.value.totalMs > 0
  ) {
    if (notificationShown.value !== `${prayerKey}-1min`) {
      showNotification(
        `${nextPrayer.value.name} prayer in 1 minute!`,
        `Time: ${nextPrayer.value.timeString}`
      );
      notificationShown.value = `${prayerKey}-1min`;
    }
  } else if (timeRemaining.value.totalMs <= 0) {
    if (notificationShown.value !== `${prayerKey}-now`) {
      showNotification(
        `${nextPrayer.value.name} prayer time!`,
        `Time: ${nextPrayer.value.timeString}`
      );
      notificationShown.value = `${prayerKey}-now`;
    }
  }
}

// Show browser notification
async function showNotification(title: string, body: string) {
  if ("Notification" in window) {
    if (Notification.permission === "granted") {
      new Notification(title, {
        body,
        icon: "/prayer-icon.png",
      });
    } else if (Notification.permission !== "denied") {
      const permission = await Notification.requestPermission();
      if (permission === "granted") {
        new Notification(title, {
          body,
          icon: "/prayer-icon.png",
        });
      }
    }
  }
}

// Request notification permission on mount
async function requestNotificationPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    await Notification.requestPermission();
  }
}

// Format time display
function formatTime(date: Date): string {
  return date.toLocaleTimeString("en-US", {
    hour12: true,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// Update current time every second
function startTimeUpdates() {
  timeInterval = setInterval(() => {
    currentTime.value = new Date();
    checkNotification();
  }, 1000);
}

// Toggle compact mode
function toggleCompactMode() {
  isCompactMode.value = !isCompactMode.value;
}

// Handle prayer name click
function onPrayerNameClick() {
  togglePrayerMode();
  // resetToAutoMode();
}

onMounted(async () => {
  await enable();
  await fetchPrayerTimes();
  await requestNotificationPermission();
  startTimeUpdates();
});

onUnmounted(() => {
  if (timeInterval) {
    clearInterval(timeInterval);
  }
});
</script>

<template>
  <main :class="['container', { compact: isCompactMode }]">
    <div class="window-controls">
      <button @click="toggleCompactMode" class="mode-toggle">
        {{ isCompactMode ? "🔍" : "📱" }}
      </button>
      <button @click="fetchPrayerTimes" class="refresh-btn" :disabled="loading">
        {{ loading ? "⟳" : "🔄" }}
      </button>
    </div>

    <div v-if="loading" class="loading">
      <p>Loading prayer times...</p>
    </div>

    <div v-else-if="error" class="error">
      <p>{{ error }}</p>
      <button @click="fetchPrayerTimes">Retry</button>
    </div>

    <div v-else-if="prayerData" class="prayer-content">
      <div class="header">
        <h1 v-if="!isCompactMode">Prayer Times</h1>
        <div class="location">
          <span
            >{{ prayerData.meta.cityAR }} - {{ prayerData.meta.cityEN }}</span
          >
        </div>
        <div class="current-time">
          {{ formatTime(currentTime) }}
        </div>
      </div>

      <div v-if="activePrayer" class="next-prayer">
        <h2 v-if="!isCompactMode">
          {{ shouldShowNextPrayer ? "Next Prayer" : "Previous Prayer" }}
        </h2>
        <div class="prayer-info">
          <div
            class="prayer-name clickable"
            @click="onPrayerNameClick"
            :title="
              shouldShowNextPrayer
                ? 'Click to show time since previous prayer'
                : 'Click to show time to next prayer'
            "
          >
            {{ activePrayer.name }}
            <span class="toggle-hint">🔄</span>
          </div>
          <div class="prayer-time">{{ activePrayer.timeString }}</div>
        </div>

        <div v-if="activeTimeDisplay" class="countdown">
          <div class="countdown-title" v-if="!isCompactMode">
            {{ shouldShowNextPrayer ? "Time Remaining" : "Time Passed" }}
          </div>
          <div class="countdown-time">
            <span class="time-unit">
              <span class="number">{{
                activeTimeDisplay.hours.toString().padStart(2, "0")
              }}</span>
              <span class="label" v-if="!isCompactMode">h</span>
            </span>
            <span class="separator">:</span>
            <span class="time-unit">
              <span class="number">{{
                activeTimeDisplay.minutes.toString().padStart(2, "0")
              }}</span>
              <span class="label" v-if="!isCompactMode">m</span>
            </span>
            <span class="separator">:</span>
            <span class="time-unit">
              <span class="number">{{
                activeTimeDisplay.seconds.toString().padStart(2, "0")
              }}</span>
              <span class="label" v-if="!isCompactMode">s</span>
            </span>
          </div>
          <div class="mode-indicator" v-if="!isCompactMode">
            <span :class="{ active: shouldShowNextPrayer }">⏭️ Next</span>
            <span :class="{ active: !shouldShowNextPrayer }">⏮️ Previous</span>
          </div>
        </div>
      </div>

      <div v-if="!isCompactMode" class="all-prayers">
        <h3>Today's Prayer Times</h3>
        <div class="prayers-grid">
          <div
            v-for="prayer in prayerOrder"
            :key="prayer"
            :class="[
              'prayer-item',
              {
                next: nextPrayer?.name === prayer,
                previous: previousPrayer?.name === prayer,
                current: activePrayer?.name === prayer,
              },
            ]"
          >
            <div class="prayer-name">{{ prayer }}</div>
            <div class="prayer-time">
              {{ prayerData.timings[prayer as keyof PrayerTimings] }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.container {
  margin: 0;
  padding: 20px;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-family: "Arial", sans-serif;
  position: relative;
  transition: all 0.3s ease;
}

.container.compact {
  min-height: auto;
  max-width: 300px;
  max-height: 200px;
  position: fixed;
  bottom: 20px;
  right: 20px;
  border-radius: 15px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  z-index: 1000;
  padding: 15px;
}

.window-controls {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  gap: 5px;
}

.mode-toggle,
.refresh-btn {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  border-radius: 50%;
  width: 35px;
  height: 35px;
  color: white;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 10;
}

.mode-toggle:hover,
.refresh-btn:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: scale(1.1);
}

.loading,
.error {
  text-align: center;
  padding: 50px;
}

.error button {
  background: rgba(255, 255, 255, 0.2);
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 5px;
  cursor: pointer;
  margin-top: 10px;
}

.header {
  text-align: center;
  margin-bottom: 30px;
}

.header h1 {
  margin: 0 0 10px 0;
  font-size: 2.5rem;
  font-weight: 300;
  text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
}

.compact .header h1 {
  display: none;
}

.location {
  font-size: 1.2rem;
  opacity: 0.9;
  margin-bottom: 10px;
}

.current-time {
  font-size: 1.5rem;
  font-weight: bold;
  background: rgba(255, 255, 255, 0.2);
  padding: 10px 20px;
  border-radius: 25px;
  display: inline-block;
}

.compact .current-time {
  font-size: 1rem;
  padding: 5px 10px;
}

.next-prayer {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-radius: 20px;
  padding: 30px;
  margin-bottom: 30px;
  text-align: center;
}

.compact .next-prayer {
  padding: 15px;
  margin-bottom: 0;
}

.next-prayer h2 {
  margin: 0 0 20px 0;
  font-size: 1.8rem;
  font-weight: 300;
}

.prayer-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 25px;
}

.compact .prayer-info {
  margin-bottom: 15px;
  flex-direction: column;
  gap: 5px;
}

.prayer-name {
  font-size: 2rem;
  font-weight: bold;
  position: relative;
}

.prayer-name.clickable {
  cursor: pointer;
  transition: all 0.3s ease;
  padding: 5px 10px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.prayer-name.clickable:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: scale(1.05);
}

.toggle-hint {
  font-size: 0.7em;
  opacity: 0.7;
  transition: opacity 0.3s ease;
}

.prayer-name.clickable:hover .toggle-hint {
  opacity: 1;
}

.compact .prayer-name {
  font-size: 1.2rem;
}

.prayer-time {
  font-size: 1.8rem;
  opacity: 0.9;
}

.compact .prayer-time {
  font-size: 1rem;
}

.countdown {
  margin-top: 20px;
}

.compact .countdown {
  margin-top: 10px;
}

.countdown-title {
  font-size: 1.2rem;
  margin-bottom: 15px;
  opacity: 0.9;
}

.countdown-time {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 10px;
  font-size: 3rem;
  font-weight: bold;
  font-family: "Courier New", monospace;
}

.compact .countdown-time {
  font-size: 1.5rem;
  gap: 5px;
}

.time-unit {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.time-unit .number {
  background: rgba(0, 0, 0, 0.3);
  padding: 10px 15px;
  border-radius: 10px;
  min-width: 60px;
  text-align: center;
}

.compact .time-unit .number {
  padding: 5px 8px;
  min-width: 30px;
  font-size: 1.2rem;
}

.time-unit .label {
  font-size: 0.8rem;
  margin-top: 5px;
  opacity: 0.7;
}

.separator {
  color: rgba(255, 255, 255, 0.7);
}

.mode-indicator {
  margin-top: 15px;
  display: flex;
  justify-content: center;
  gap: 20px;
  font-size: 0.9rem;
}

.mode-indicator span {
  opacity: 0.5;
  transition: opacity 0.3s ease;
}

.mode-indicator span.active {
  opacity: 1;
  font-weight: bold;
}

.all-prayers {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-radius: 20px;
  padding: 30px;
}

.all-prayers h3 {
  text-align: center;
  margin: 0 0 25px 0;
  font-size: 1.5rem;
  font-weight: 300;
}

.prayers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 15px;
}

.prayer-item {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 15px;
  padding: 20px;
  text-align: center;
  transition: all 0.3s ease;
}

.prayer-item:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: translateY(-5px);
}

.prayer-item.next {
  background: rgba(76, 175, 80, 0.3);
  border: 2px solid rgba(76, 175, 80, 0.5);
  box-shadow: 0 0 20px rgba(76, 175, 80, 0.3);
}

.prayer-item.previous {
  background: rgba(255, 152, 0, 0.3);
  border: 2px solid rgba(255, 152, 0, 0.5);
  box-shadow: 0 0 20px rgba(255, 152, 0, 0.3);
}

.prayer-item.current {
  background: rgba(255, 255, 255, 0.3);
  border: 2px solid rgba(255, 255, 255, 0.5);
  box-shadow: 0 0 20px rgba(255, 255, 255, 0.3);
}

.prayer-item .prayer-name {
  font-size: 1.2rem;
  font-weight: bold;
  margin-bottom: 10px;
}

.prayer-item .prayer-time {
  font-size: 1.1rem;
  opacity: 0.9;
}

@media (max-width: 768px) {
  .container {
    padding: 15px;
  }

  .prayers-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .countdown-time {
    font-size: 2rem;
  }

  .time-unit .number {
    min-width: 45px;
    padding: 8px 10px;
  }
}
</style>
