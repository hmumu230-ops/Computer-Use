#!/usr/bin/env node
// Postinstall: install a wrapper that execs python3 bridge.py for pi to spawn.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const helperDir = path.join(os.homedir(), ".pi", "agent", "helpers", "linux-computer-use");
const helperPath = path.join(helperDir, "bridge");
const bridgePy = path.join(rootDir, "bridge", "bridge.py");

const isPostinstall = process.argv.includes("--postinstall");

function which(cmd) {
	const r = spawnSync("sh", ["-lc", `command -v ${cmd}`], { encoding: "utf8" });
	return r.status === 0 ? r.stdout.trim() : null;
}

async function main() {
	if (process.platform !== "linux") {
		const msg = `[pcul] non-linux platform (${process.platform}); skipping helper setup.`;
		if (isPostinstall) { console.warn(msg); return; }
		throw new Error(msg);
	}

	await fs.mkdir(helperDir, { recursive: true });
	// Prefer system python3 so PyGObject (gi) is available; venvs usually lack it.
	const py = which("/usr/bin/python3") ? "/usr/bin/python3" : "python3";
	const wrapper = `#!/usr/bin/env bash
exec ${py} ${JSON.stringify(bridgePy)} "$@"
`;
	await fs.writeFile(helperPath, wrapper, { mode: 0o755 });
	await fs.chmod(helperPath, 0o755);
	console.log(`[pcul] installed helper -> ${helperPath}`);

	const missing = [];
	for (const tool of ["python3", "xdotool", "wmctrl", "scrot"]) {
		if (!which(tool)) missing.push(tool);
	}
	if (missing.length) {
		console.warn(
			`[pcul] missing baseline deps: ${missing.join(", ")}.\n` +
			`        sudo apt-get install -y python3 python3-gi gir1.2-atspi-2.0\n` +
			`        X11: xdotool wmctrl scrot xclip | Wayland: ydotool wl-clipboard grim`,
		);
	}
}

main().catch((e) => {
	const msg = e instanceof Error ? e.message : String(e);
	if (isPostinstall) { console.warn(`[pcul] postinstall skipped: ${msg}`); process.exit(0); }
	console.error(msg); process.exit(1);
});
