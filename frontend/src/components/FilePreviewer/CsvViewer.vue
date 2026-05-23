<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import * as XLSX from "xlsx";

const props = defineProps<{
	url: string;
	fileName: string;
	scale: number;
}>();

interface LoadState {
	status: "loading" | "loaded" | "error";
	headers: string[];
	rows: string[][];
	error?: string;
}

const state = ref<LoadState>({ status: "loading", headers: [], rows: [] });

const fontSize = computed(() => `${Math.max(0.5, props.scale) * 0.8125}rem`);

const isExcel = computed(() => /\.xlsx?$/i.test(props.fileName));

let controller: AbortController | null = null;

async function load() {
	controller?.abort();
	controller = new AbortController();
	const { signal } = controller;

	state.value = { status: "loading", headers: [], rows: [] };
	try {
		const res = await fetch(props.url, { signal });
		if (!res.ok) throw new Error(`HTTP ${res.status}`);

		if (isExcel.value) {
			const buf = await res.arrayBuffer();
			const wb = XLSX.read(new Uint8Array(buf), { type: "array" });
			const sheetName = wb.SheetNames[0] || "";
			const sheet = wb.Sheets[sheetName];
			const data = XLSX.utils.sheet_to_json<string[]>(sheet, {
				header: 1,
				defval: "",
			});
			if (signal.aborted) return;
			const headers =
				data.length > 0 ? (data[0] as string[]).map((c) => String(c)) : [];
			const rows = data
				.slice(1)
				.map((row) => (row as string[]).map((c) => String(c)));
			state.value = { status: "loaded", headers, rows };
		} else {
			const text = await res.text();
			if (signal.aborted) return;
			const lines = text.trim().split("\n");
			const delimiter = props.fileName.endsWith(".tsv") ? "\t" : ",";
			const parseRow = (line: string) => {
				const cells: string[] = [];
				let cell = "";
				let inQuotes = false;
				for (let i = 0; i < line.length; i++) {
					const ch = line[i];
					if (inQuotes) {
						if (ch === '"') {
							if (line[i + 1] === '"') {
								cell += '"';
								i++;
							} else {
								inQuotes = false;
							}
						} else {
							cell += ch;
						}
					} else {
						if (ch === '"') {
							inQuotes = true;
						} else if (ch === delimiter) {
							cells.push(cell.trim());
							cell = "";
						} else {
							cell += ch;
						}
					}
				}
				cells.push(cell.trim());
				return cells;
			};
			const parsed = lines.map(parseRow);
			const headers = parsed.length > 0 ? parsed[0] : [];
			const rows = parsed.slice(1);
			state.value = { status: "loaded", headers, rows };
		}
	} catch (err) {
		if (signal.aborted) return;
		state.value = {
			status: "error",
			headers: [],
			rows: [],
			error: err instanceof Error ? err.message : "加载失败",
		};
	}
}

watch(() => props.url, load, { immediate: true });

onBeforeUnmount(() => {
	controller?.abort();
});
</script>

<template>
	<div
		class="w-full max-w-7xl max-h-full overflow-auto rounded-lg bg-[#1e1e2e] shadow-2xl"
		:style="{ fontSize }"
	>
		<div v-if="state.status === 'loading'" class="flex items-center justify-center h-32 text-white/40 text-sm">
			加载中...
		</div>
		<div v-else-if="state.status === 'error'" class="flex items-center justify-center h-32 text-red-400 text-sm">
			{{ state.error }}
		</div>
		<table v-else class="w-full border-collapse text-sm text-white/90">
			<thead class="sticky top-0 z-10">
				<tr class="bg-white/10">
					<th
						v-for="(h, i) in state.headers"
						:key="i"
						class="px-3 py-2 text-left font-medium text-white/70 border-b border-white/10 whitespace-nowrap"
					>{{ h }}</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="(row, ri) in state.rows"
					:key="ri"
					class="border-b border-white/5 hover:bg-white/5 transition-colors"
				>
					<td
						v-for="(cell, ci) in row"
						:key="ci"
						class="px-3 py-1.5 max-w-[300px] truncate"
					>{{ cell }}</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>

<style scoped>
table {
	font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
}
</style>
