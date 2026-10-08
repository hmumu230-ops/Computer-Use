// Subprocess manager for the Linux bridge helper.
// Newline-delimited JSON request/response over stdio.
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import os from "node:os";
import path from "node:path";

const HELPER_PATH = path.join(os.homedir(), ".pi", "agent", "helpers", "linux-computer-use", "bridge");
const TIMEOUT_MS = 15000;

interface Pending {
	resolve: (v: any) => void;
	reject: (e: Error) => void;
	timer: NodeJS.Timeout;
}

let helper: ChildProcessWithoutNullStreams | undefined;
let stdoutBuf = "";
let seq = 0;
const pending = new Map<string, Pending>();

function rejectAll(err: Error) {
	for (const [id, p] of pending) {
		clearTimeout(p.timer);
		p.reject(err);
		pending.delete(id);
	}
}

function onLine(line: string) {
	const trimmed = line.trim();
	if (!trimmed) return;
	let msg: any;
	try {
		msg = JSON.parse(trimmed);
	} catch {
		return;
	}
	const id = msg.id as string | undefined;
	if (!id) return;
	const p = pending.get(id);
	if (!p) return;
	clearTimeout(p.timer);
	pending.delete(id);
	if (msg.ok) p.resolve(msg.result);
	else p.reject(new Error(String(msg.error ?? "bridge error")));
}

function ensureHelper(): ChildProcessWithoutNullStreams {
	if (helper && helper.exitCode === null && !helper.killed) return helper;
	const child = spawn(HELPER_PATH, [], { stdio: ["pipe", "pipe", "pipe"] });
	child.stdout.setEncoding("utf8");
	child.stderr.setEncoding("utf8");
	child.stdin.setDefaultEncoding("utf8");
	child.stdout.on("data", (chunk: string) => {
		stdoutBuf += chunk;
		let idx;
		while ((idx = stdoutBuf.indexOf("\n")) >= 0) {
			const line = stdoutBuf.slice(0, idx);
			stdoutBuf = stdoutBuf.slice(idx + 1);
			onLine(line);
		}
	});
	child.stderr.on("data", (chunk: string) => {
		if (process.env.PCUL_DEBUG) process.stderr.write(`[pcul] ${chunk}`);
	});
	child.on("error", (e) => {
		if (helper === child) helper = undefined;
		rejectAll(new Error(`bridge crashed: ${e.message}`));
	});
	child.on("exit", (code, sig) => {
		if (helper === child) helper = undefined;
		rejectAll(new Error(`bridge exited (${sig ?? code})`));
	});
	helper = child;
	stdoutBuf = "";
	return child;
}

export async function send<T = any>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
	const id = `r${++seq}`;
	const child = ensureHelper();
	return new Promise<T>((resolve, reject) => {
		const timer = setTimeout(() => {
			pending.delete(id);
			reject(new Error(`bridge timeout: ${cmd}`));
		}, TIMEOUT_MS);
		pending.set(id, { resolve, reject, timer });
		child.stdin.write(`${JSON.stringify({ id, cmd, ...args })}\n`);
	});
}

export function stopBridge(): void {
	if (helper) {
		try {
			helper.stdin.end();
			helper.kill();
		} catch {}
		helper = undefined;
	}
	rejectAll(new Error("bridge stopped"));
}

// Typed wrappers — arg names mirror bridge/bridge.py command handlers.
export const capabilities = () => send("capabilities");
export const probe = () => send("probe");
export const listWindows = () => send("list_windows");
export const windowFocus = (opts: { ref: string }) => send("window_focus", opts);
export const windowClose = (opts: { ref: string; confirmToken?: string }) => send("window_close", opts);
export const windowMove = (opts: { ref: string; x?: number; y?: number; w?: number; h?: number }) => send("window_move", opts);
export const windowState = (opts: { ref: string; state: string; on?: boolean }) => send("window_state", opts);
export const desktops = () => send("desktops");
export const switchDesktop = (opts: { index: number }) => send("switch_desktop", opts);
export const windowToDesktop = (opts: { ref: string; index: number }) => send("window_to_desktop", opts);
export const cursorPos = () => send("cursor_pos");
export const snapshot = (opts: { window?: string; region?: any; tree?: boolean; pid?: number } = {}) => send("snapshot", opts);
export const screenshot = (opts: { window?: string; region?: any } = {}) => send("screenshot", opts);
export const findElements = (opts: { role?: string; name?: string; states?: string[]; limit?: number; pid?: number }) => send("find_elements", opts);
export const findText = (opts: { text: string; region?: any; limit?: number }) => send("find_text", opts);
export const waitFor = (opts: { role?: string; name?: string; event?: string; timeout?: number }) => send("wait_for", opts);
export const waitForText = (opts: { text: string; timeout?: number }) => send("wait_for_text", opts);
export const act = (opts: { ref: string; verb?: string }) => send("act", opts);
export const click = (opts: { ref?: string; x?: number; y?: number; button?: string; clickCount?: number; method?: string }) => send("click", opts);
export const typeText = (opts: { text: string; delayMs?: number }) => send("type_text", opts);
export const setText = (opts: { ref: string; text: string }) => send("set_text", opts);
export const setValue = (opts: { ref: string; value: number }) => send("set_value", opts);
export const select = (opts: { ref: string; index: number }) => send("select", opts);
export const keypress = (opts: { keys: string[] }) => send("keypress", opts);
export const scroll = (opts: { ref?: string; x?: number; y?: number; scrollY?: number; scrollX?: number }) => send("scroll", opts);
export const moveMouse = (opts: { ref?: string; x?: number; y?: number }) => send("move_mouse", opts);
export const drag = (opts: { from?: string; to?: string; x1?: number; y1?: number; x2?: number; y2?: number; button?: string }) => send("drag", opts);
export const computerActions = (opts: { actions: any[]; failFast?: boolean }) => send("computer_actions", opts);
export const clipboardGet = (opts: { what?: string } = {}) => send("clipboard_get", opts);
export const clipboardSet = (opts: { text?: string; pngBase64?: string; files?: string[] }) => send("clipboard_set", opts);
export const notify = (opts: { title: string; body?: string; urgency?: string; icon?: string; timeoutMs?: number }) => send("notify", opts);
export const launchApp = (opts: { target: string }) => send("launch_app", opts);

// Format helper for tool results
import type { AgentToolResult } from "./types.ts";

export function ok(summary: string, details?: unknown): AgentToolResult {
	return { content: [{ type: "text", text: summary }], details: details as any };
}

export function okWithImage(summary: string, pngBase64: string, details?: unknown): AgentToolResult {
	return {
		content: [
			{ type: "text", text: summary },
			{ type: "image", data: pngBase64, mimeType: "image/png" },
		],
		details: details as any,
	};
}

export function err(message: string): AgentToolResult {
	return { content: [{ type: "text", text: `error: ${message}` }] };
}
