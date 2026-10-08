"""PowerShell tool — shell/command execution."""

from mcp.types import ToolAnnotations
from windows_mcp import safety
from windows_mcp.infrastructure import with_analytics
from windows_mcp.powershell import PowerShellExecutor
from fastmcp import Context


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="PowerShell",
        description="Shell/command execution. Keywords: shell, run, execute, cmd, terminal, command line, script. A comprehensive system tool for executing any PowerShell commands. Use it to navigate the file system, manage files and processes, and execute system-level operations. Capable of accessing web content (e.g., via Invoke-WebRequest), interacting with network resources, and performing complex administrative tasks. This tool provides full access to the underlying operating system capabilities, making it the primary interface for system automation, scripting, and deep system interaction. Non-read-only commands may require confirmation — repeat the same command with confirm='<token>'.",
        annotations=ToolAnnotations(
            title="PowerShell",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    @with_analytics(get_analytics, "Powershell-Tool")
    def powershell_tool(
        command: str,
        timeout: int = 30,
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        try:
            preview = " ".join(command.split())[:120]
            gated = safety.gate(
                f"powershell:{safety.digest(command)}",
                f"execute PowerShell command '{preview}'",
                confirm,
                dangerous=safety.command_dangerous(command),
            )
            if gated:
                return gated
            response, status_code = PowerShellExecutor.execute_command(command, timeout)
            if safety.command_dangerous(command):
                safety.audit(f"powershell:{safety.digest(command)}", preview)
            return f"Response: {response}\nStatus Code: {status_code}"
        except Exception:
            raise
