<script setup lang="ts">
import { cn } from "@/lib/utils";
import {
	ScrollAreaCorner,
	ScrollAreaRoot,
	type ScrollAreaRootProps,
	ScrollAreaViewport,
} from "reka-ui";
import { type HTMLAttributes, computed } from "vue";
import ScrollBar from "./ScrollBar.vue";

const props = defineProps<
	ScrollAreaRootProps & { class?: HTMLAttributes["class"] }
>();

const delegatedProps = computed(() => {
	const { class: _, ...delegated } = props;
	return delegated;
});
</script>

<template>
  <ScrollAreaRoot v-bind="delegatedProps" :class="cn('relative overflow-hidden', props.class)">
    <ScrollAreaViewport class="scroll-area-viewport h-full w-full rounded-[inherit]">
      <slot />
    </ScrollAreaViewport>
    <ScrollBar />
    <ScrollAreaCorner />
  </ScrollAreaRoot>
</template>

<style scoped>
.scroll-area-viewport {
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
}
</style>
