<script setup lang="ts">
import FilePreviewer from "@/components/FilePreviewer/FilePreviewer.vue";
import Toaster from "@/components/ui/toast/Toaster.vue";
</script>

<template>
  <Toaster />
  <router-view />
  <FilePreviewer />
</template>