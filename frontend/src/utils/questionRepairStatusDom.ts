const STYLE_ID = "q-repair-status-style";
const LINE_CLASS = "q-repair-status-line";
const CHIP_CLASS = "q-repair-status-chip";

function addStyle() {
	if (document.getElementById(STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
.${LINE_CLASS}{margin-top:.28rem;display:flex;align-items:center;min-height:1.15rem;}
.${CHIP_CLASS}{display:inline-flex;align-items:center;max-width:100%;border-radius:999px;border:1px solid;padding:.08rem .45rem;font-size:10px;font-weight:700;line-height:1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:0 1px 8px rgba(15,23,42,.04);}
.${CHIP_CLASS}[data-level="info"]{color:#2563eb;border-color:#bfdbfe;background:rgba(239,246,255,.92);}
.${CHIP_CLASS}[data-level="warn"]{color:#b45309;border-color:#fde68a;background:rgba(255,251,235,.95);box-shadow:0 0 12px rgba(245,158,11,.12);}
.${CHIP_CLASS}[data-level="bad"]{color:#dc2626;border-color:#fecaca;background:rgba(254,242,242,.95);box-shadow:0 0 12px rgba(239,68,68,.10);}
`;
	document.head.appendChild(style);
}

function countText(text: string, keys: string[]) {
	return Math.max(
		0,
		...keys.map((key) => text.split(key).length - 1),
	);
}

function statusFromText(text: string): { text: string; level: "info" | "warn" | "bad" } | null {
	const n = countText(text, ["返回：代码执行", "执行错误", "代码执行错误", "Traceback"]);
	const count = Math.max(n, 1);
	const judging = text.includes("协调者后台错误判别已启动") && !text.includes("协调者后台错误判别完成");
	const sameKind = text.includes("same_error=true") || text.includes("同类错误");
	const rewrite = text.includes("should_restart=true") || text.includes("切换新 Coder") || text.includes("准备换新 Coder") || text.includes("重新组织方案");
	const backup = text.includes("CoderAgent 备用") || text.includes("代码 备用") || text.includes("备用 Coder");

	if (backup) return { text: "反复出错，备用 Coder 重写中", level: "warn" };
	if (rewrite) return { text: "反复出错，准备换新 Coder 重写", level: "bad" };
	if (judging) return { text: `第 ${count} 次改错 · 协调者后台判别中`, level: "warn" };
	if (sameKind) return { text: `第 ${count} 次改错 · 同类错误，按建议继续修`, level: "warn" };
	if (n > 0) return { text: `第 ${n} 次改错`, level: n >= 3 ? "warn" : "info" };
	return null;
}

function ensureLine(summary: HTMLElement) {
	let line = summary.querySelector<HTMLElement>(`.${LINE_CLASS}`);
	if (line) return line;
	line = document.createElement("div");
	line.className = LINE_CLASS;
	const chip = document.createElement("span");
	chip.className = CHIP_CLASS;
	line.appendChild(chip);
	const main = summary.querySelector<HTMLElement>(".min-w-0.flex-1");
	(main || summary).appendChild(line);
	return line;
}

function refreshOne(shell: HTMLDetailsElement) {
	const summary = shell.querySelector<HTMLElement>("summary");
	if (!summary) return;
	const s = statusFromText(shell.textContent || "");
	const old = summary.querySelector<HTMLElement>(`.${LINE_CLASS}`);
	if (!s) {
		old?.remove();
		return;
	}
	const line = ensureLine(summary);
	const chip = line.querySelector<HTMLElement>(`.${CHIP_CLASS}`);
	if (!chip) return;
	chip.textContent = s.text;
	chip.dataset.level = s.level;
	chip.title = s.text;
}

let pending = false;
function refresh() {
	if (pending) return;
	pending = true;
	requestAnimationFrame(() => {
		pending = false;
		document.querySelectorAll<HTMLDetailsElement>("details.question-group-shell").forEach(refreshOne);
	});
}

export function installQuestionRepairStatusDomPatch() {
	if (typeof document === "undefined") return;
	addStyle();
	refresh();
	new MutationObserver(refresh).observe(document.body, { childList: true, subtree: true, characterData: true });
	window.setInterval(refresh, 1000);
}
