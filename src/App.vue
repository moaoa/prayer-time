<script setup lang="ts"></script>

<template>
  <router-view />
</template>

<style>
html,
body,
#app {
  height: 100%;
}

body {
  margin: 0;
  padding: 0;
  /* WebView2 follows the Windows color scheme and restyles native buttons.
     This app paints its own light-on-purple controls. */
  color-scheme: light;
}
</style>
