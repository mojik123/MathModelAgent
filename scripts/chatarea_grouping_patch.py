"""Patch ChatArea.vue: restructure agent grouping.
1. Remove writer from questionGroupsData regex
2. Remove writer from topLevelItems regex
3. Add writerGroupsData computed
4. Update indexedGroupIdSet to include writer IDs
5. Add writer_group kind to TopLevelItem type
6. Add writer_group to topLevelItems output
7. Add writer_group card template after question_group card
"""

path = r"C:\Users\mojik\Desktop\mm-auto-3\MathModelAgent-main\frontend\src\components\ChatArea.vue"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ---- Fix 1: questionGroupsData regex (2nd occurrence, offset ~60073) ----
old = "/^(?:sub_coordinator|modeler|coder|writer)_(\\d+)$/"
new = "/^(?:sub_coordinator|modeler|coder)_(\\d+)$/"
# Replace 2nd occurrence only
idx1 = content.find(old)
idx2 = content.find(old, idx1 + 1)
if idx2 >= 0:
    content = content[:idx2] + new + content[idx2 + len(old):]
    print("Fix 1 (questionGroupsData regex): OK")
else:
    print("Fix 1: FAIL")

# ---- Fix 2: topLevelItems regex (now becomes the 2nd occurrence) ----
# After fix 1, there are still occurrences. Find the one in topLevelItems.
# The topLevelItems one is preceded by "} else {\n\t\t\tconst m = group.id.match"
old_tli_context = '} else {\n\t\t\tconst m = group.id.match(\n\t\t\t\t/^(?:sub_coordinator|modeler|coder|writer)_(\\d+)$/,\n\t\t\t);'
new_tli_context = '} else {\n\t\t\tconst m = group.id.match(\n\t\t\t\t/^(?:sub_coordinator|modeler|coder)_(\\d+)$/,\n\t\t\t);'
if old_tli_context in content:
    content = content.replace(old_tli_context, new_tli_context)
    print("Fix 2 (topLevelItems regex): OK")
else:
    print("Fix 2: FAIL")
    # Show what's around the expected location
    marker = 'topLevelItems'
    mi = content.find('const topLevelItems')
    if mi >= 0:
        snippet = content[mi:mi+500]
        # Find the regex in this snippet
        ri = snippet.find('sub_coordinator|modeler|coder|writer')
        if ri >= 0:
            print(f"  Found in topLevelItems at relative offset {ri}")
            print(f"  Context: {repr(snippet[ri-80:ri+100])}")

# ---- Fix 3: Add writerGroupsData after questionGroupsData ----
# Find end of questionGroupsData (the .map(...) block closing)
old_qg = "\t\t});\n});\n\nconst indexedGroupIdSet"
if old_qg in content:
    insert = """\t\t});
\t});

\t// 论文写作组：收集所有 WriterAgent，独立于求解子问题组
\tconst writerGroupsData = computed<AgentGroup[]>(() => {
\t\treturn agentGroups.value
\t\t\t.filter((group) => /^writer_\\d+$/.test(group.id))
\t\t\t.sort((a, b) => {
\t\t\t\tconst ma = a.id.match(/^writer_(\\d+)$/);
\t\t\t\tconst mb = b.id.match(/^writer_(\\d+)$/);
\t\t\t\treturn (ma ? Number(ma[1]) : 0) - (mb ? Number(mb[1]) : 0);
\t\t\t});
\t});

const indexedGroupIdSet"""
    content = content.replace(old_qg, insert)
    print("Fix 3 (writerGroupsData): OK")
else:
    print("Fix 3: FAIL")

# ---- Fix 4: Add writer IDs to indexedGroupIdSet ----
old_idset = """const indexedGroupIdSet = computed(() => {
\tconst ids = new Set<string>();
\tfor (const qg of questionGroupsData.value) {
\t\tfor (const g of qg.groups) ids.add(g.id);
\t}
\treturn ids;
});"""
new_idset = """const indexedGroupIdSet = computed(() => {
\tconst ids = new Set<string>();
\tfor (const qg of questionGroupsData.value) {
\t\tfor (const g of qg.groups) ids.add(g.id);
\t}
\tfor (const wg of writerGroupsData.value) ids.add(wg.id);
\treturn ids;
});"""
if old_idset in content:
    content = content.replace(old_idset, new_idset)
    print("Fix 4 (indexedGroupIdSet): OK")
else:
    print("Fix 4: FAIL")
    # Debug
    mi = content.find('indexedGroupIdSet = computed')
    if mi >= 0:
        print(f"  Found at {mi}")
        print(f"  Text: {repr(content[mi:mi+200])}")

# ---- Fix 5: Add writer_group to TopLevelItem type ----
old_type = """type TopLevelItem =
\t| { kind: "group"; group: AgentGroup }
\t| (QuestionGroupData & { kind: "question_group" });"""
new_type = """type TopLevelItem =
\t| { kind: "group"; group: AgentGroup }
\t| (QuestionGroupData & { kind: "question_group" })
\t| { kind: "writer_group"; groups: AgentGroup[] };"""
if old_type in content:
    content = content.replace(old_type, new_type)
    print("Fix 5 (TopLevelItem type): OK")
else:
    print("Fix 5: FAIL")
    mi = content.find('type TopLevelItem')
    if mi >= 0:
        print(f"  Found at {mi}")
        print(f"  Text: {repr(content[mi:mi+200])}")

# ---- Fix 6: Add writer_group to topLevelItems ----
old_tli_return = "\t\treturn items;\n\t});"
new_tli_return = """\t\tif (writerGroupsData.value.length > 0) {
\t\t\titems.push({ kind: "writer_group", groups: writerGroupsData.value });
\t\t}
\t\treturn items;
\t});"""
if old_tli_return in content:
    content = content.replace(old_tli_return, new_tli_return)
    print("Fix 6 (topLevelItems writer_group): OK")
else:
    print("Fix 6: FAIL")

# ---- Fix 7: Add writer_group template after question_group template ----
# Find the closing of question_group template section (after </details> for question_group)
# and before </template> of the v-for
old_qg_end = """\t\t\t\t\t\t</details>
\t\t\t\t\t</template>
\t\t\t\t</div>
\t\t\t</div>
\t\t</div>

\t</div>
</template>"""

if old_qg_end in content:
    writer_template = """\t\t\t\t\t\t</details>

\t\t\t\t\t\t<!-- 论文写作组卡片 -->
\t\t\t\t\t\t<details
\t\t\t\t\t\t\tv-else-if=\"item.kind === 'writer_group'\"
\t\t\t\t\t\t\tclass=\"writer-group-shell group glass-card rounded-2xl border border-emerald-200/40 bg-emerald-50/30 backdrop-blur-md shadow-[0_4px_24px_rgba(16,185,129,0.06),0_0_0_1px_rgba(255,255,255,0.5)_inset] transition-all duration-300\"
\t\t\t\t\t\t\t:open=\"isDetailOpen('writer_group', 'main')\"
\t\t\t\t\t\t>
\t\t\t\t\t\t\t<summary
\t\t\t\t\t\t\t\tclass=\"flex cursor-pointer list-none items-start gap-3 px-4 py-3.5\"
\t\t\t\t\t\t\t\t@click.prevent=\"toggleDetailOpen('writer_group', 'main')\"
\t\t\t\t\t\t\t>
\t\t\t\t\t\t\t\t<div class=\"pt-0.5\">
\t\t\t\t\t\t\t\t\t<div class=\"flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-100 ring-2 ring-emerald-200/50\">
\t\t\t\t\t\t\t\t\t\t<PenLine class=\"h-4 w-4 text-emerald-600\" />
\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t<div class=\"min-w-0 flex-1\">
\t\t\t\t\t\t\t\t\t<div class=\"flex min-w-0 items-center gap-2\">
\t\t\t\t\t\t\t\t\t\t<span class=\"truncate text-sm font-semibold text-slate-900\">论文写作</span>
\t\t\t\t\t\t\t\t\t\t<span class=\"shrink-0 font-mono text-[11px] text-slate-500\">{{ item.groups.length }} 个写作 Agent</span>
\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t<div class=\"mt-1 text-xs text-slate-600\">
\t\t\t\t\t\t\t\t\t\t各问建模完成后统一撰写论文各章节
\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t<div class=\"flex shrink-0 items-center gap-2 pt-0.5 text-[11px] text-slate-500\">
\t\t\t\t\t\t\t\t\t<span>{{ item.groups.length }} 个 Agent</span>
\t\t\t\t\t\t\t\t\t<ChevronDown class=\"h-4 w-4 transition group-open:rotate-180\" />
\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t</summary>

\t\t\t\t\t\t\t<!-- 展开后的写作 Agent 卡片列表 -->
\t\t\t\t\t\t\t<div class=\"writer-group-body border-t border-emerald-200/30 px-3 py-2 space-y-2\">
\t\t\t\t\t\t\t\t<details
\t\t\t\t\t\t\t\t\tv-for=\"writerGroup in item.groups\"
\t\t\t\t\t\t\t\t\t:key=\"writerGroup.id\"
\t\t\t\t\t\t\t\t\t:data-group-id=\"writerGroup.id\"
\t\t\t\t\t\t\t\t\tclass=\"group glass-card rounded-xl border border-white/20 bg-white/50 backdrop-blur-sm shadow-[0_2px_12px_rgba(0,0,0,0.02)] transition-all duration-300 hover:shadow-[0_4px_16px_rgba(59,130,246,0.08)] hover:border-blue-200/30\"
\t\t\t\t\t\t\t\t\t:class=\"{ 'active-agent-glow': writerGroup.id === activeGroupId && writerGroup.status !== 'done', 'card-pulse': pulseGroupIds.has(writerGroup.id) || writerGroup.actions.some(a => newActionIds.has(a.id)) }\"
\t\t\t\t\t\t\t\t\t:open=\"isDetailOpen('writer_group', writerGroup.id)\"
\t\t\t\t\t\t\t\t>
\t\t\t\t\t\t\t\t\t<summary
\t\t\t\t\t\t\t\t\t\tclass=\"flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5\"
\t\t\t\t\t\t\t\t\t\t@click.prevent=\"toggleDetailOpen('writer_group', writerGroup.id)\"
\t\t\t\t\t\t\t\t\t>
\t\t\t\t\t\t\t\t\t\t<div class=\"pt-0.5\">
\t\t\t\t\t\t\t\t\t\t\t<PenLine class=\"h-4 w-4 text-emerald-600\" />
\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t\t<div class=\"min-w-0 flex-1\">
\t\t\t\t\t\t\t\t\t\t\t<div class=\"flex min-w-0 items-center gap-1.5\">
\t\t\t\t\t\t\t\t\t\t\t\t<span class=\"truncate text-xs font-semibold text-slate-800\">{{ writerGroup.name }}</span>
\t\t\t\t\t\t\t\t\t\t\t\t<span class=\"rounded-full border px-1.5 py-0.5 text-[10px]\" :class=\"statusClass(writerGroup.status)\">{{ statusLabel(writerGroup.status) }}</span>
\t\t\t\t\t\t\t\t\t\t\t\t<span class=\"shrink-0 font-mono text-[10px] text-slate-500\">{{ formatDuration(writerGroup.durationMs) }}</span>
\t\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t\t\t<div class=\"mt-0.5 flex items-center gap-1.5 overflow-hidden\">
\t\t\t\t\t\t\t\t\t\t\t\t<span class=\"work-state-pill\" :class=\"groupWorkPillClass(writerGroup.id)\">
\t\t\t\t\t\t\t\t\t\t\t\t\t{{ groupWorkStateLabel(writerGroup.id) }}
\t\t\t\t\t\t\t\t\t\t\t\t</span>
\t\t\t\t\t\t\t\t\t\t\t\t<span v-if=\"groupWorkStatus[writerGroup.id]?.state === 'commanded'\" class=\"work-dot\" />
\t\t\t\t\t\t\t\t\t\t\t\t<span class=\"truncate text-[10px]\" :class=\"groupWorkClass(writerGroup.id)\">
\t\t\t\t\t\t\t\t\t\t\t\t\t{{ groupWorkStatus[writerGroup.id]?.text ?? writerGroup.role }}
\t\t\t\t\t\t\t\t\t\t\t\t</span>
\t\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t\t<div class=\"flex shrink-0 items-center gap-1.5 text-[10px] text-slate-500\">
\t\t\t\t\t\t\t\t\t\t\t<span>{{ writerGroup.actions.length }} 条</span>
\t\t\t\t\t\t\t\t\t\t\t<ChevronDown class=\"h-3.5 w-3.5 transition group-open:rotate-180\" />
\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t</summary>

\t\t\t\t\t\t\t\t\t<div class=\"group-action-shell\">
\t\t\t\t\t\t\t\t\t\t<div :ref=\"(element) => setGroupScrollRef(writerGroup.id, element)\" class=\"group-action-window border-t border-slate-100\">
\t\t\t\t\t\t\t\t\t\t\t<div class=\"divide-y divide-white/10\">
\t\t\t\t\t\t\t\t\t\t\t\t<div
\t\t\t\t\t\t\t\t\t\t\t\t\tv-for=\"action in writerGroup.actions\"
\t\t\t\t\t\t\t\t\t\t\t\t\t:key=\"action.id\"
\t\t\t\t\t\t\t\t\t\t\t\t\tclass=\"action-line px-3 py-2\"
\t\t\t\t\t\t\t\t\t\t\t\t\t:class=\"{ 'card-merge': newActionIds.has(action.id) }\"
\t\t\t\t\t\t\t\t\t\t\t\t>
\t\t\t\t\t\t\t\t\t\t\t\t\t<div class=\"flex min-w-0 items-center gap-2\">
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<span class=\"shrink-0 font-mono text-[10px] text-slate-400\">{{ action.timeLabel }}</span>
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<span v-if=\"action.status === 'running'\" class=\"shrink-0 font-mono text-[10px] text-blue-500\">{{ formatDuration(action.durationMs) }}</span>
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<LoaderCircle v-if=\"action.status === 'running'\" class=\"h-3.5 w-3.5 shrink-0 animate-spin text-blue-600\" />
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<CheckCircle2 v-else-if=\"action.status === 'done'\" class=\"h-3.5 w-3.5 shrink-0 text-slate-300\" />
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<CircleAlert v-else-if=\"action.status === 'warning'\" class=\"h-3.5 w-3.5 shrink-0 text-amber-600\" />
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<CircleX v-else-if=\"action.status === 'error'\" class=\"h-3.5 w-3.5 shrink-0 text-red-600\" />
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<Clock3 v-else class=\"h-3.5 w-3.5 shrink-0 text-slate-300\" />
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<span class=\"shrink min-w-0 truncate text-[0.72rem]\" :class=\"actionTitleChipClass(action)\">{{ action.title }}</span>
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<span v-if=\"action.status === 'running'\" class=\"shrink-0 rounded-full border border-blue-200 bg-blue-50 px-1 py-0.5 text-[9px] text-blue-700\">进行中</span>
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<span v-else-if=\"action.status === 'warning' || action.status === 'error'\" class=\"shrink-0 rounded-full border px-1 py-0.5 text-[9px]\" :class=\"statusClass(action.status)\">{{ statusLabel(action.status) }}</span>
\t\t\t\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t\t\t</details>
\t\t\t\t\t\t\t</div>
\t\t\t\t\t\t</details>

\t\t\t\t\t</template>
\t\t\t\t</div>
\t\t\t</div>
\t\t</div>

\t</div>
</template>"""
    content = content.replace(old_qg_end, writer_template)
    print("Fix 7 (writer_group template): OK")
else:
    print("Fix 7: FAIL - template end not found")
    # Try to find what's there
    mi = content.rfind('</template>')
    if mi >= 0:
        print(f"  Last </template> at offset {mi}")
        print(f"  Context: {repr(content[mi-150:mi+20])}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("\nDone.")
