<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from "vue";
import { enable } from "@tauri-apps/plugin-autostart";
import prayerTimesData from "./assets/prayer_times.json";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import { platform } from "@tauri-apps/plugin-os";
import { Command } from "@tauri-apps/plugin-shell";

// Declare Tauri global type
declare global {
  interface Window {
    __TAURI_INTERNALS__?: any;
  }
}

interface PrayerTimings {
  fajer: string;
  sunrise: string;
  dhuhr: string;
  asr: string;
  maghrib: string;
  isha: string;
}

interface PrayerDay {
  date: string;
  fajer: string;
  sunrise: string;
  dhuhr: string;
  asr: string;
  maghrib: string;
  isha: string;
}

const prayerData = ref<Record<string, PrayerDay[]>>(prayerTimesData);

const cities = computed(() => Object.keys(prayerData.value));

const defaultCity = "Tripoli";

const storedCity = localStorage.getItem("selectedCity");

const selectedCity = ref(
  storedCity && cities.value.includes(storedCity)
    ? storedCity
    : cities.value.includes(defaultCity)
    ? defaultCity
    : cities.value[0] || ""
);

watch(selectedCity, (newCity) => {
  localStorage.setItem("selectedCity", newCity);
});

const currentTime = ref(new Date());
const isCompactMode = ref(false);
const notificationShown = ref<string>("");
const isManualToggle = ref(false);
const showNextPrayer = ref(true);

let timeInterval: number | null = null;

const prayerOrder = ["fajer", "sunrise", "dhuhr", "asr", "maghrib", "isha"];

const todayPrayerTimings = computed(() => {
  if (!selectedCity.value || !prayerData.value[selectedCity.value]) {
    return null;
  }
  const now = new Date();
  const month = now.getMonth() + 1;
  const day = now.getDate();
  const formattedDate = `${month}-${day}`;
  const todayData = prayerData.value[selectedCity.value].find(
    (day) => day.date === formattedDate
  );
  return todayData;
});

function prayerTimeToDate(timeStr: string): Date {
  const [hoursAndMinutes, unit] = timeStr.split(" ");
  const [hours, minutes] = hoursAndMinutes.split(":").map(Number);
  const date = new Date();
  date.setHours(hours, minutes, 0, 0);
  if (unit === "pm") {
    date.setHours(date.getHours() + 12);
  }
  return date;
}

const nextPrayer = computed(() => {
  if (!todayPrayerTimings.value) return null;

  const now = currentTime.value;

  for (const prayer of prayerOrder) {
    const prayerTime = prayerTimeToDate(
      todayPrayerTimings.value[prayer as keyof PrayerTimings]
    );

    if (prayerTime > now) {
      return {
        name: prayer,
        time: prayerTime,
        timeString: todayPrayerTimings.value[prayer as keyof PrayerTimings],
      };
    }
  }

  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const fajrTime = prayerTimeToDate(todayPrayerTimings.value.fajer);
  fajrTime.setDate(tomorrow.getDate());

  return {
    name: "fajer",
    time: fajrTime,
    timeString: todayPrayerTimings.value.fajer,
  };
});

const previousPrayer = computed(() => {
  if (!todayPrayerTimings.value) return null;

  const now = currentTime.value;
  let lastPrayer = null;

  for (const prayer of prayerOrder) {
    const prayerTime = prayerTimeToDate(
      todayPrayerTimings.value[prayer as keyof PrayerTimings]
    );

    if (prayerTime <= now) {
      lastPrayer = {
        name: prayer,
        time: prayerTime,
        timeString: todayPrayerTimings.value[prayer as keyof PrayerTimings],
      };
    } else {
      break;
    }
  }

  if (!lastPrayer) {
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const ishaTime = prayerTimeToDate(todayPrayerTimings.value.isha);
    ishaTime.setDate(yesterday.getDate());

    return {
      name: "isha",
      time: ishaTime,
      timeString: todayPrayerTimings.value.isha,
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
  const currentPlatform = platform();

  if (currentPlatform == "linux") {
    const result = Command.create("notify-send", [title, body]).execute();

    console.log(result);
    return;
  }

  let permissionGranted = await isPermissionGranted();
  if (!permissionGranted) {
    const permission = await requestPermission();
    permissionGranted = permission === "granted";
  }
  console.log("Permission granted:", permissionGranted, title, body);
  if (permissionGranted) {
    sendNotification({ title, body, icon: "/prayer-icon.png" });
  }
}

// Request notification permission on mount
async function requestNotificationPermission() {
  let permissionGranted = await isPermissionGranted();
  if (!permissionGranted) {
    await requestPermission();
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
}

onMounted(async () => {
  await enable();
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
    </div>

    <div v-if="todayPrayerTimings" class="prayer-content">
      <div class="header">
        <h1 v-if="!isCompactMode">Prayer Times</h1>
        <div class="location">
          <select v-model="selectedCity">
            <option v-for="city in cities" :key="city" :value="city">
              {{ city }}
            </option>
          </select>
        </div>
        <button
          @click="showNotification('test', 'the body of the notification')"
        >
          notifications test
        </button>
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
              {{ todayPrayerTimings[prayer as keyof PrayerTimings] }}
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="loading">
      <p>No prayer times found for today.</p>
    </div>
  </main>
</template>

<style>
body {
  margin: 0;
  padding: 0;
}
</style>
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
