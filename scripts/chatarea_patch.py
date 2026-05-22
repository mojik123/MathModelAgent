"""Patch ChatArea.vue with the changes described in ChatArea修改说明.md."""
import re

path = r"C:\Users\mojik\Desktop\mm-auto-3\MathModelAgent-main\frontend\src\components\ChatArea.vue"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ---- Patch 5: Replace header area ----
old_header = '<div class="glass-header border-b border-white/20 px-4 py-3">\n\t\t\t\t<div class="flex items-center justify-between gap-3">\n\t\t\t\t\t<div class="min-w-0">\n\t\t\t\t\t\t<div class="flex items-center gap-2 text-sm font-semibold text-slate-950">\n\t\t\t\t\t\t\t<ListChecks class="h-4 w-4 text-blue-600" />\n\t\t\t\t\t\t\tAgent 执行状态\n\t\t\t\t\t\t</div>\n\t\t\t\t\t\t<div class="mt-1 truncate text-xs text-slate-500">\n\t\t\t\t\t\t\t<template v-if="isTaskCompleted">\n\t\t\t\t\t\t\t\t{{ finishedAgentCount }}/{{ agentGroups.length }} 个 Agent 已完成\n\t\t\t\t\t\t\t</template>\n\t\t\t\t\t\t\t<template v-else>\n\t\t\t\t\t\t\t\t{{ runningAction ? "动作中" : "等待中" }} \xb7 {{ agentGroups.length }} 个 Agent 有动作记录\n\t\t\t\t\t\t\t</template>\n\t\t\t\t\t\t\t<span v-if="runningAction"> \xb7 当前：{{ runningAction.agent }} / {{ runningAction.title }}</span>\n\t\t\t\t\t\t</div>\n\t\t\t\t\t</div>\n\t\t\t\t\t<div\n\t\t\t\t\t\tv-if="runningAction"\n\t\t\t\t\t\tclass="glass-pill flex shrink-0 items-center gap-2 rounded-full border border-blue-300/40 bg-blue-400/10 backdrop-blur px-2.5 py-1 text-xs text-blue-600 shadow-[0_0_12px_rgba(59,130,246,0.15)]"\n\t\t\t\t\t>\n\t\t\t\t\t\t<LoaderCircle class="h-3.5 w-3.5 animate-spin" />\n\t\t\t\t\t\t<span class="max-w-[14rem] truncate">{{ runningAction.agent }}</span>\n\t\t\t\t\t\t<span class="font-mono">{{ formatDuration(runningAction.durationMs) }}</span>\n\t\t\t\t\t</div>\n\t\t\t\t</div>\n\t\t\t</div>'

new_header = '<div class="glass-header border-b border-white/20 px-4 py-3">\n\t\t\t\t<div class="min-w-0">\n\t\t\t\t\t<div class="flex items-center gap-2 text-sm font-semibold text-slate-950">\n\t\t\t\t\t\t<ListChecks class="h-4 w-4 text-blue-600" />\n\t\t\t\t\t\tAgent 执行状态\n\t\t\t\t\t</div>\n\n\t\t\t\t\t<div v-if="runningAgentPills.length" class="parallel-agent-pills mt-2">\n\t\t\t\t\t\t<div\n\t\t\t\t\t\t\tv-for="pill in runningAgentPills"\n\t\t\t\t\t\t\t:key="pill.id"\n\t\t\t\t\t\t\tclass="parallel-agent-pill"\n\t\t\t\t\t\t\t:class="{\n\t\t\t\t\t\t\t\t\'parallel-agent-pill-working\': pill.state === \'working\' || pill.status === \'running\',\n\t\t\t\t\t\t\t\t\'parallel-agent-pill-commanded\': pill.state === \'commanded\',\n\t\t\t\t\t\t\t}"\n\t\t\t\t\t\t\t:title="`${pill.name} / ${pill.text}`"\n\t\t\t\t\t\t>\n\t\t\t\t\t\t\t<LoaderCircle\n\t\t\t\t\t\t\t\tv-if="pill.state === \'working\' || pill.status === \'running\'"\n\t\t\t\t\t\t\t\tclass="h-3.5 w-3.5 shrink-0 animate-spin"\n\t\t\t\t\t\t\t/>\n\t\t\t\t\t\t\t<Clock3 v-else class="h-3.5 w-3.5 shrink-0" />\n\t\t\t\t\t\t\t<span class="parallel-agent-pill-name">{{ pill.name }}</span>\n\t\t\t\t\t\t\t<span class="parallel-agent-pill-detail">{{ pill.text }}</span>\n\t\t\t\t\t\t\t<span class="parallel-agent-pill-time">{{ formatDuration(pill.durationMs) }}</span>\n\t\t\t\t\t\t</div>\n\t\t\t\t\t</div>\n\t\t\t\t</div>\n\t\t\t</div>'

# Instead of exact matching, use regex to find and replace the header
# Find the header by looking for the unique "glass-header" class and ListChecks
header_start = content.find('<div class="glass-header border-b border-white/20 px-4 py-3">')
if header_start >= 0:
    print(f"Found glass-header at offset {header_start}")
    # Find the matching closing </div> for this header
    # The header is a simple structure - find the next "main-scroll-shell" which comes right after
    next_section = content.find('main-scroll-shell', header_start)
    if next_section >= 0:
        # Find the </div> that closes the header by looking backwards from main-scroll-shell
        # The header ends with </div>\n\n\n\n\t\t\t\t<div class="main-scroll-shell"
        # Let's find the </div> just before the empty lines
        search_pos = next_section
        # Go back through newlines
        while search_pos > header_start and content[search_pos] in ('\n', '\t', ' ', '\r'):
            search_pos -= 1
        # Now find the </div> end
        close_tag = content.rfind('</div>', header_start, search_pos + 1)
        if close_tag >= 0:
            # This </div> closes the flex inner div, need one more
            close_tag2 = content.rfind('</div>', header_start, close_tag)
            if close_tag2 >= 0:
                old_header_actual = content[header_start:close_tag2 + 6]
                print(f"Header length: {len(old_header_actual)} chars")
                content = content[:header_start] + new_header + content[close_tag2 + 6:]
                print("Patch 5 (header): OK")
            else:
                print("Patch 5: could not find second </div>")
        else:
            print("Patch 5: could not find closing </div>")
    else:
        print("Patch 5: main-scroll-shell not found")
else:
    print("Patch 5: glass-header not found")


# ---- Patch 6: Agent group card -> manual open ----
# Find: :open="item.group.id === effectiveOpenGroupId"
old_agent_open = ':open="item.group.id === effectiveOpenGroupId"'
new_agent_open = ':open="isDetailOpen(\'group\', item.group.id)"'
if old_agent_open in content:
    content = content.replace(old_agent_open, new_agent_open, 1)
    print("Patch 6a (agent :open): OK")
else:
    print("Patch 6a: NOT FOUND")

# Find: @toggle="handleAgentGroupToggle(item.group.id, $event)"
old_agent_toggle = '@toggle="handleAgentGroupToggle(item.group.id, $event)"'
new_agent_toggle = ''
if old_agent_toggle in content:
    # Remove the @toggle line entirely - we need to keep the > at end
    # The pattern is: @toggle="..."\n\t\t\t\t\t\t>
    # Replace with just >
    old_with_close = old_agent_toggle + '\n\t\t\t\t\t\t>'
    new_with_close = '>'
    if old_with_close in content:
        content = content.replace(old_with_close, new_with_close, 1)
        print("Patch 6b (agent @toggle): OK")
    else:
        print("Patch 6b: @toggle pattern with close not found")
else:
    print("Patch 6b: @toggle NOT FOUND")

# Find: @click="markAgentGroupUserToggle(item.group.id)"
old_agent_click = '@click="markAgentGroupUserToggle(item.group.id)"'
new_agent_click = '@click.prevent="toggleDetailOpen(\'group\', item.group.id)"'
if old_agent_click in content:
    content = content.replace(old_agent_click, new_agent_click, 1)
    print("Patch 6c (agent summary click): OK")
else:
    print("Patch 6c: NOT FOUND")

# ---- Patch 7: Question group card -> manual open ----
old_qg_open = ':open="isQuestionGroupExpanded(item.index, item.groups)"'
new_qg_open = ':open="isDetailOpen(\'question_group\', item.index)"'
if old_qg_open in content:
    content = content.replace(old_qg_open, new_qg_open, 1)
    print("Patch 7a (qg :open): OK")
else:
    print("Patch 7a: NOT FOUND")

old_qg_toggle = '@toggle="handleQuestionGroupToggle(item.index, $event)"'
if old_qg_toggle in content:
    old_qg_with_close = old_qg_toggle + '\n\t\t\t\t\t\t\t>\n\t\t\t\t\t\t\t\t<summary class="flex cursor-pointer list-none items-start gap-3 px-4 py-3.5">'
    new_qg_with_close = '>\n\t\t\t\t\t\t\t\t<summary\n\t\t\t\t\t\t\t\t\tclass="flex cursor-pointer list-none items-start gap-3 px-4 py-3.5"\n\t\t\t\t\t\t\t\t\t@click.prevent="toggleDetailOpen(\'question_group\', item.index)"\n\t\t\t\t\t\t\t\t>'
    if old_qg_with_close in content:
        content = content.replace(old_qg_with_close, new_qg_with_close, 1)
        print("Patch 7b (qg @toggle + summary): OK")
    else:
        print("Patch 7b: qg toggle+summary pattern not found")
else:
    print("Patch 7b: qg @toggle NOT FOUND")

# ---- Patch 8: Sub-agent card -> manual open ----
old_sub_open = 'open\n\t\t\t\t\t\t\t\t\t>'
new_sub_open = ':open="isDetailOpen(\'sub_group\', subGroup.id)"\n\t\t\t\t\t\t\t\t\t>'
if old_sub_open in content:
    content = content.replace(old_sub_open, new_sub_open, 1)
    print("Patch 8a (sub open): OK")
    # Now fix the summary
    old_sub_summary = '<summary class="flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5">'
    new_sub_summary = '<summary\n\t\t\t\t\t\t\t\t\t\tclass="flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5"\n\t\t\t\t\t\t\t\t\t\t@click.prevent="toggleDetailOpen(\'sub_group\', subGroup.id)"\n\t\t\t\t\t\t\t\t\t>'
    if old_sub_summary in content:
        content = content.replace(old_sub_summary, new_sub_summary, 1)
        print("Patch 8b (sub summary): OK")
    else:
        print("Patch 8b: sub summary NOT FOUND (may already be replaced)")
else:
    # Try alternate pattern - sub card has specific class
    print("Patch 8a: sub open NOT FOUND with exact pattern, trying alternate...")
    # The sub card has unique class combo
    alt_pattern = 'hover:border-blue-200/30"\n\t\t\t\t\t\t\t\t\t:class="{ \'active-agent-glow\': subGroup.id === activeGroupId && subGroup.status !== \'done\', \'card-pulse\': pulseGroupIds.has(subGroup.id) || subGroup.actions.some(a => newActionIds.has(a.id)) }"\n\t\t\t\t\t\t\t\t\topen\n\t\t\t\t\t\t\t\t>'
    alt_replacement = 'hover:border-blue-200/30"\n\t\t\t\t\t\t\t\t\t:class="{ \'active-agent-glow\': subGroup.id === activeGroupId && subGroup.status !== \'done\', \'card-pulse\': pulseGroupIds.has(subGroup.id) || subGroup.actions.some(a => newActionIds.has(a.id)) }"\n\t\t\t\t\t\t\t\t\t:open="isDetailOpen(\'sub_group\', subGroup.id)"\n\t\t\t\t\t\t\t\t>'
    if alt_pattern in content:
        content = content.replace(alt_pattern, alt_replacement, 1)
        print("Patch 8a (sub open alt): OK")
        # Also fix summary
        old_sub_summary2 = '<summary class="flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5">'
        new_sub_summary2 = '<summary\n\t\t\t\t\t\t\t\t\tclass="flex cursor-pointer list-none items-start gap-2.5 px-3 py-2.5"\n\t\t\t\t\t\t\t\t\t@click.prevent="toggleDetailOpen(\'sub_group\', subGroup.id)"\n\t\t\t\t\t\t\t\t>'
        if old_sub_summary2 in content:
            content = content.replace(old_sub_summary2, new_sub_summary2, 1)
            print("Patch 8b (sub summary alt): OK")
        else:
            print("Patch 8b alt: sub summary NOT FOUND")
    else:
        print("Patch 8a alt: NOT FOUND either")

# ---- Patch 9: Add CSS ----
css_to_add = """
/* ====== 并行 Agent 胶囊 ====== */
.parallel-agent-pills {
	display: flex;
	align-items: center;
	min-height: 2.25rem;
	max-width: 100%;
	overflow-x: auto;
	overflow-y: visible;
	padding: 0.2rem 0.4rem 0.2rem 0;
}

.parallel-agent-pill {
	--pill-width: 10rem;
	position: relative;
	z-index: 1;
	display: inline-flex;
	align-items: center;
	gap: 0.35rem;
	width: var(--pill-width);
	max-width: var(--pill-width);
	min-width: var(--pill-width);
	height: 1.9rem;
	border-radius: 999px;
	border: 1px solid rgba(147, 197, 253, 0.55);
	background: rgba(239, 246, 255, 0.88);
	backdrop-filter: blur(12px);
	-webkit-backdrop-filter: blur(12px);
	padding: 0 0.65rem;
	font-size: 0.72rem;
	line-height: 1;
	color: #2563eb;
	box-shadow: 0 0 14px rgba(59, 130, 246, 0.14);
	transition:
		margin 220ms ease,
		width 220ms ease,
		max-width 220ms ease,
		min-width 220ms ease,
		transform 220ms ease,
		opacity 220ms ease,
		box-shadow 220ms ease;
}

.parallel-agent-pill + .parallel-agent-pill {
	margin-left: calc(var(--pill-width) * -0.7);
}

.parallel-agent-pills:hover .parallel-agent-pill + .parallel-agent-pill {
	margin-left: 0.35rem;
}

.parallel-agent-pills:hover .parallel-agent-pill {
	opacity: 0.68;
}

.parallel-agent-pills .parallel-agent-pill:hover {
	z-index: 20;
	width: 18rem;
	max-width: 18rem;
	min-width: 18rem;
	opacity: 1;
	transform: translateY(-1px);
	box-shadow: 0 0 18px rgba(59, 130, 246, 0.22), 0 6px 18px rgba(15, 23, 42, 0.08);
}

.parallel-agent-pill-working {
	border-color: rgba(96, 165, 250, 0.65);
	background: linear-gradient(90deg, rgba(239, 246, 255, 0.96), rgba(238, 242, 255, 0.88));
	color: #2563eb;
}

.parallel-agent-pill-commanded {
	border-color: rgba(251, 191, 36, 0.62);
	background: linear-gradient(90deg, rgba(255, 251, 235, 0.96), rgba(254, 243, 199, 0.88));
	color: #a16207;
}

.parallel-agent-pill-name {
	min-width: 0;
	max-width: 8.5rem;
	overflow: hidden;
	white-space: nowrap;
	text-overflow: ellipsis;
	font-weight: 700;
}

.parallel-agent-pill-detail {
	display: none;
	min-width: 0;
	overflow: hidden;
	white-space: nowrap;
	text-overflow: ellipsis;
	font-weight: 500;
}

.parallel-agent-pill:hover .parallel-agent-pill-name {
	max-width: 7rem;
}

.parallel-agent-pill:hover .parallel-agent-pill-detail {
	display: inline;
	max-width: 7rem;
}

.parallel-agent-pill-time {
	margin-left: auto;
	font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
	font-size: 0.66rem;
	opacity: 0.82;
}
"""

anchor = '.agent-status-collapsed .glass-header {\n\tpadding-top: 0.5rem;\n\tpadding-bottom: 0.5rem;\n}'
if anchor in content:
    content = content.replace(anchor, anchor + css_to_add, 1)
    print("Patch 9 (CSS): OK")
else:
    print("Patch 9 (CSS anchor 1): NOT FOUND")
    anchor2 = '.agent-status-collapsed .main-scroll-shell {'
    if anchor2 in content:
        content = content.replace(anchor2, css_to_add + '\n' + anchor2, 1)
        print("Patch 9 (CSS anchor 2): OK")
    else:
        print("Patch 9: BOTH anchors NOT FOUND")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

# Final validation
checks = {
    "should NOT exist": [
        "effectiveOpenGroupId",
        "handleAgentGroupToggle",
        "isQuestionGroupExpanded",
        "handleQuestionGroupToggle",
        "expandedQuestionGroupIds",
        "userCollapsedQuestionGroupIds",
        "markAgentGroupUserToggle",
        "openGroupId",
        "lastActiveGroupId",
    ],
    "should EXIST": [
        "manualOpenDetailIds",
        "isDetailOpen",
        "toggleDetailOpen",
        "runningAgentPills",
        "parallel-agent-pills",
        "parallel-agent-pill",
        "@click.prevent",
    ],
}

print("\n=== Final Validation ===")
all_ok = True
for name, terms in checks.items():
    for term in terms:
        found = term in content
        if name == "should NOT exist" and found:
            print(f"  FAIL: '{term}' {name}")
            all_ok = False
        elif name == "should EXIST" and not found:
            print(f"  FAIL: '{term}' {name}")
            all_ok = False

if all_ok:
    print("  ALL CHECKS PASSED")
else:
    print("  Some checks failed - review above")
