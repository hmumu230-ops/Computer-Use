// Pi extension: registers Linux computer-use tools (X11 + Wayland backends).
import type { ExtensionAPI, ToolDef, AgentToolResult } from "../src/types.ts";
import * as b from "../src/bridge.ts";
import { ok, okWithImage, err, stopBridge } from "../src/bridge.ts";

// Plain JSON-schema params (kept terse for token efficiency).
const REF = { type: "string", description: "@eN element or @wN window ref" };
const XY = { x: { type: "number" }, y: { type: "number" } };
const REGION = {
	type: "object",
	properties: { ...XY, w: { type: "number" }, h: { type: "number" } },
	description: "{x,y,w,h} logical pixels",
};

const S = {
	empty: { type: "object", properties: {}, additionalProperties: false },
	scopedShot: {
		type: "object",
		properties: { window: { type: "string", description: "@wN" }, region: REGION },
		additionalProperties: false,
	},
	snapshot: {
		type: "object",
		properties: {
			window: { type: "string", description: "@wN" },
			region: REGION,
			tree: { type: "boolean", description: "include AT-SPI elements (default true)" },
			pid: { type: "number", description: "restrict AT-SPI walk to this pid" },
		},
		additionalProperties: false,
	},
	click: {
		type: "object",
		properties: {
			ref: REF, ...XY,
			button: { type: "string", enum: ["left", "right", "middle"] },
			clickCount: { type: "number" },
			method: { type: "string", enum: ["auto", "action", "synthetic"] },
		},
	},
	keypress: {
		type: "object",
		properties: { keys: { type: "array", items: { type: "string" }, minItems: 1 } },
		required: ["keys"],
	},
	computerActions: {
		type: "object",
		properties: {
			actions: { type: "array", minItems: 1, maxItems: 20 },
			failFast: { type: "boolean" },
		},
		required: ["actions"],
	},
};

async function safe<T>(fn: () => Promise<T>): Promise<{ ok: true; v: T } | { ok: false; e: string }> {
	try { return { ok: true, v: await fn() }; }
	catch (e) { return { ok: false, e: e instanceof Error ? e.message : String(e) }; }
}

function g(w: any): string {
	const r = w.geometry ?? {};
	return `${r.w ?? "?"}x${r.h ?? "?"}@${r.x ?? "?"},${r.y ?? "?"}`;
}

function fmtWindows(ws: any[]): string {
	return ws.map((w) => `${w.ref} pid=${w.pid} ${g(w)}${w.focused ? " *" : ""}  ${w.title}`).join("\n");
}

function fmtElements(es: any[]): string {
	if (!es.length) return "(no AX elements)";
	return es.slice(0, 80).map((t) => {
		const r = t.bbox ?? {};
		return `${t.ref} ${t.role} "${t.name}" ${r.w ?? "?"}x${r.h ?? "?"}@${r.x ?? "?"},${r.y ?? "?"}`;
	}).join("\n");
}

function t(name: string, description: string, parameters: any,
	exec: (p: any) => Promise<AgentToolResult>): ToolDef {
	return { name, description, parameters, executionMode: "sequential", execute: (_id, p) => exec(p ?? {}) };
}

const tools: ToolDef[] = [
	// --- diagnostics ---
	t("capabilities", "Bridge version, session type, compositor, available backends/tools.", S.empty,
		async () => {
			const r = await safe(b.capabilities);
			return r.ok ? ok(JSON.stringify(r.v)) : err(r.e);
		}),
	t("probe", "Probe environment: init/session/DE/tool availability/permission hints.", S.empty,
		async () => {
			const r = await safe(b.probe);
			return r.ok ? ok(JSON.stringify(r.v)) : err(r.e);
		}),
	// --- windows ---
	t("list_windows", "List windows (@wN, title, pid, geometry, focus). X11/Wayland backends.", S.empty,
		async () => {
			const r = await safe(b.listWindows);
			if (!r.ok) return err(r.e);
			const ws = (r.v as any).windows as any[];
			return ok(`${ws.length} windows:\n${fmtWindows(ws)}`, { windows: ws });
		}),
	t("window_focus", "Raise+focus @wN.",
		{ type: "object", properties: { ref: REF }, required: ["ref"] },
		async (p) => { const r = await safe(() => b.windowFocus(p)); return r.ok ? ok("focused") : err(r.e); }),
	t("window_close", "Close @wN (confirm-gated).",
		{ type: "object", properties: { ref: REF, confirmToken: { type: "string" } }, required: ["ref"] },
		async (p) => { const r = await safe(() => b.windowClose(p)); return r.ok ? ok("closed") : err(r.e); }),
	t("window_move", "Move/resize @wN; pass any of x,y,w,h.",
		{ type: "object", properties: { ref: REF, ...XY, w: { type: "number" }, h: { type: "number" } }, required: ["ref"] },
		async (p) => { const r = await safe(() => b.windowMove(p)); return r.ok ? ok("moved") : err(r.e); }),
	t("window_state", "Set @wN state: minimize|maximize|fullscreen|above|shaded|sticky|floating (+on=false to unset).",
		{ type: "object", properties: { ref: REF, state: { type: "string" }, on: { type: "boolean" } }, required: ["ref", "state"] },
		async (p) => { const r = await safe(() => b.windowState(p)); return r.ok ? ok(`${p.state}=${p.on !== false}`) : err(r.e); }),
	t("desktops", "List virtual desktops/workspaces.", S.empty,
		async () => { const r = await safe(b.desktops); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	t("switch_desktop", "Switch to desktop index.",
		{ type: "object", properties: { index: { type: "number" } }, required: ["index"] },
		async (p) => { const r = await safe(() => b.switchDesktop(p)); return r.ok ? ok("switched") : err(r.e); }),
	t("window_to_desktop", "Move @wN to desktop index.",
		{ type: "object", properties: { ref: REF, index: { type: "number" } }, required: ["ref", "index"] },
		async (p) => { const r = await safe(() => b.windowToDesktop(p)); return r.ok ? ok("moved") : err(r.e); }),
	t("cursor_pos", "Pointer position (X11/KDE/Hyprland only; errors on GNOME/sway).", S.empty,
		async () => { const r = await safe(b.cursorPos); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	// --- capture & find ---
	t("snapshot", "Screenshot + AT-SPI element list; mints fresh @eN/@wN refs.", S.snapshot,
		async (p) => {
			const r = await safe(() => b.snapshot(p));
			if (!r.ok) return err(r.e);
			const v = r.v as any;
			const summary = `state=${v.stateId} gen=${v.generation} ${v.width}x${v.height}@${v.scale}x (${v.backend})\n${fmtWindows(v.windows ?? [])}\n${fmtElements(v.elements ?? [])}`;
			return okWithImage(summary, v.pngBase64, { stateId: v.stateId, elements: v.elements });
		}),
	t("screenshot", "PNG only (window @wN, region, or full screen); no element scan.", S.scopedShot,
		async (p) => {
			const r = await safe(() => b.screenshot(p));
			if (!r.ok) return err(r.e);
			const v = r.v as any;
			return okWithImage(`${v.width}x${v.height}@${v.scale}x (${v.backend})`, v.pngBase64, { stateId: v.stateId });
		}),
	t("find_elements", "Search AT-SPI tree: role/name/states filters; returns @eN refs.",
		{ type: "object", properties: { role: { type: "string" }, name: { type: "string" }, states: { type: "array", items: { type: "string" } }, limit: { type: "number" }, pid: { type: "number" } } },
		async (p) => {
			const r = await safe(() => b.findElements(p));
			if (!r.ok) return err(r.e);
			const es = (r.v as any).elements as any[];
			return ok(`${es.length} elements:\n${fmtElements(es)}`, { elements: es });
		}),
	t("find_text", "OCR/AT-SPI text search → synthetic @eN refs (clickable).",
		{ type: "object", properties: { text: { type: "string" }, region: REGION, limit: { type: "number" } }, required: ["text"] },
		async (p) => {
			const r = await safe(() => b.findText(p));
			if (!r.ok) return err(r.e);
			const ms = (r.v as any).matches as any[];
			return ok(`${ms.length} matches:\n` + ms.map((m) => `${m.ref} "${m.text}" via ${m.via} ${JSON.stringify(m.bbox)}`).join("\n"), { matches: ms });
		}),
	t("wait_for", "Wait for element (role/name) or AT-SPI event; timeout in seconds.",
		{ type: "object", properties: { role: { type: "string" }, name: { type: "string" }, event: { type: "string" }, timeout: { type: "number" } } },
		async (p) => { const r = await safe(() => b.waitFor(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	t("wait_for_text", "Wait until text appears on screen; timeout in seconds.",
		{ type: "object", properties: { text: { type: "string" }, timeout: { type: "number" } }, required: ["text"] },
		async (p) => { const r = await safe(() => b.waitForText(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	// --- actions ---
	t("act", "Semantic action on @eN ONLY (press|toggle|expand|show_menu|...). No coordinates.",
		{ type: "object", properties: { ref: REF, verb: { type: "string" } }, required: ["ref"] },
		async (p) => { const r = await safe(() => b.act(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	t("click", "Click @eN (action first, coords fallback) or raw x,y. button/clickCount/method optional.", S.click,
		async (p) => { const r = await safe(() => b.click(p)); return r.ok ? ok(`clicked (${(r.v as any).method})`) : err(r.e); }),
	t("type_text", "Type text into the focused control. delayMs optional.",
		{ type: "object", properties: { text: { type: "string" }, delayMs: { type: "number" } }, required: ["text"] },
		async (p) => { const r = await safe(() => b.typeText(p)); return r.ok ? ok(`typed ${(r.v as any).typed} chars (${(r.v as any).backend})`) : err(r.e); }),
	t("set_text", "Replace @eN text via AT-SPI EditableText; falls back to focus+ctrl+a+type.",
		{ type: "object", properties: { ref: REF, text: { type: "string" } }, required: ["ref", "text"] },
		async (p) => { const r = await safe(() => b.setText(p)); return r.ok ? ok(`set (${(r.v as any).used ?? "ok"})`) : err(r.e); }),
	t("set_value", "Set @eN numeric value via AT-SPI Value (sliders/spinboxes).",
		{ type: "object", properties: { ref: REF, value: { type: "number" } }, required: ["ref", "value"] },
		async (p) => { const r = await safe(() => b.setValue(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	t("select", "Select child index of @eN (lists/trees/combos).",
		{ type: "object", properties: { ref: REF, index: { type: "number" } }, required: ["ref", "index"] },
		async (p) => { const r = await safe(() => b.select(p)); return r.ok ? ok("selected") : err(r.e); }),
	t("keypress", 'Press keys, e.g. ["enter"], ["ctrl+a"], ["ctrl+l","enter"].', S.keypress,
		async (p) => { const r = await safe(() => b.keypress(p)); return r.ok ? ok(`pressed (${(r.v as any).backend})`) : err(r.e); }),
	t("scroll", "Scroll at @eN or x,y by scrollY/scrollX pixels (~40px/tick).",
		{ type: "object", properties: { ref: REF, ...XY, scrollY: { type: "number" }, scrollX: { type: "number" } } },
		async (p) => { const r = await safe(() => b.scroll(p)); return r.ok ? ok("scrolled") : err(r.e); }),
	t("move_mouse", "Move pointer to @eN center or x,y.",
		{ type: "object", properties: { ref: REF, ...XY } },
		async (p) => { const r = await safe(() => b.moveMouse(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	t("drag", "Drag ref→ref or x1,y1→x2,y2. Wayland synthetic DnD is restricted — prefer clipboard.",
		{ type: "object", properties: { from: REF, to: REF, x1: { type: "number" }, y1: { type: "number" }, x2: { type: "number" }, y2: { type: "number" }, button: { type: "string" } } },
		async (p) => { const r = await safe(() => b.drag(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	t("computer_actions", "Run a sequence of {click|type_text|set_text|keypress|scroll|act|drag} actions.", S.computerActions,
		async (p) => {
			const r = await safe(() => b.computerActions(p));
			if (!r.ok) return err(r.e);
			const trace = (r.v as any).trace as any[];
			const lines = trace.map((s, i) => `${i}: ${s.type} ${s.ok ? "ok" : "fail: " + s.error}`);
			return ok(lines.join("\n"), { trace });
		}),
	// --- misc ---
	t("clipboard_get", "Read clipboard: what=auto|text|image|files.",
		{ type: "object", properties: { what: { type: "string" } } },
		async (p) => { const r = await safe(() => b.clipboardGet(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
	t("clipboard_set", "Write clipboard: text | pngBase64 | files[].",
		{ type: "object", properties: { text: { type: "string" }, pngBase64: { type: "string" }, files: { type: "array", items: { type: "string" } } } },
		async (p) => { const r = await safe(() => b.clipboardSet(p)); return r.ok ? ok("clipboard set") : err(r.e); }),
	t("notify", "Desktop notification (notify-send / D-Bus).",
		{ type: "object", properties: { title: { type: "string" }, body: { type: "string" }, urgency: { type: "string", enum: ["low", "normal", "critical"] }, icon: { type: "string" }, timeoutMs: { type: "number" } }, required: ["title"] },
		async (p) => { const r = await safe(() => b.notify(p)); return r.ok ? ok("notified") : err(r.e); }),
	t("launch_app", "Launch .desktop id, path, URL, or shell command.",
		{ type: "object", properties: { target: { type: "string" } }, required: ["target"] },
		async (p) => { const r = await safe(() => b.launchApp(p)); return r.ok ? ok(JSON.stringify(r.v)) : err(r.e); }),
];

export default function computerUseExtension(pi: ExtensionAPI): void {
	for (const tool of tools) {
		try { pi.registerTool(tool); }
		catch (e) {
			if (!/conflicts with/.test(e instanceof Error ? e.message : "")) throw e;
		}
	}
	if (pi.on) pi.on("session_shutdown", () => stopBridge());
}
