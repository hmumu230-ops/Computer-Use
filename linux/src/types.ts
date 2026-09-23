// Minimal type stubs for pi-coding-agent surface we use.
// Avoids hard dep at typecheck time when peer dep isn't installed.
export type ImageMode = "auto" | "always" | "never";

export interface AgentToolResultContent {
	type: "text" | "image";
	text?: string;
	data?: string;
	mimeType?: string;
}

export interface AgentToolResult<D = unknown> {
	content: AgentToolResultContent[];
	details?: D;
}

export type AgentToolUpdateCallback = (chunk: unknown) => void;

export interface ExtensionContext {
	cwd?: string;
	hasUI?: boolean;
	[key: string]: unknown;
}

export interface ToolDef {
	name: string;
	label?: string;
	description: string;
	executionMode?: "sequential" | "parallel";
	parameters: unknown;
	execute: (
		toolCallId: string,
		params: any,
		signal: AbortSignal | undefined,
		onUpdate: AgentToolUpdateCallback | undefined,
		ctx: ExtensionContext,
	) => Promise<AgentToolResult>;
}

export interface ExtensionAPI {
	registerTool(spec: ToolDef): void;
	registerCommand?(name: string, opts: any): void;
	on?(event: string, handler: (...args: any[]) => any): void;
}
