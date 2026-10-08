"""Notification tool — Windows toast notifications."""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field
from windows_mcp.infrastructure import with_analytics
from fastmcp import Context
from windows_mcp import notifications


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="Notification",
        description="Sends a Windows toast notification with a title and message. app_id is the target app's Application User Model ID; leave the default 'Microsoft.Windows.Explorer' to show it under Windows Explorer.",
        annotations=ToolAnnotations(
            title="Notification",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics, "Notification-Tool")
    def notification_tool(
        title: Annotated[
            str,
            Field(description="The title/heading of the toast notification."),
        ],
        message: Annotated[
            str,
            Field(description="The body text of the toast notification displayed below the title."),
        ],
        app_id: Annotated[
            str,
            Field(
                description="Application User Model ID the toast is attributed to (e.g. 'Microsoft.WindowsTerminal_8wekyb3d8bbwe!App'). Default shows it under Windows Explorer.",
            ),
        ] = "Microsoft.Windows.Explorer",
        ctx: Context = None,
    ) -> str:
        try:
            return notifications.send_notification(title, message, app_id)
        except Exception:
            raise
