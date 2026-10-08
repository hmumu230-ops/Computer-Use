"""MultiSelect and MultiEdit tools — batch element interaction."""

import json

from mcp.types import ToolAnnotations
from windows_mcp.desktop import actions
from windows_mcp.infrastructure import with_analytics
from windows_mcp.refs import RefStore
from windows_mcp.refs.locator import ElementLocator
from fastmcp import Context


def _as_loc(value: list | str | None) -> list | None:
    """Coerce a JSON-stringified list back to a list (Claude Desktop workaround)."""
    if value is None or isinstance(value, list):
        return value
    return json.loads(value)


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="MultiSelect",
        description="Selects multiple items such as files, folders, or checkboxes if press_ctrl=True, or performs multiple clicks if False. Pass refs (list of @eN refs — preferred), locs (list of coordinates), or labels (list of UI element labels/ids).",
        annotations=ToolAnnotations(
            title="MultiSelect",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics, "Multi-Select-Tool")
    def multi_select_tool(
        locs: list[list[int]] | str | None = None,
        labels: list[int] | str | None = None,
        refs: list[str] | str | None = None,
        press_ctrl: bool | str = True,
        ctx: Context = None,
    ) -> str:
        desktop = get_desktop()
        locs = _as_loc(locs)
        labels = _as_loc(labels)
        refs = _as_loc(refs)
        if locs is None and labels is None and refs is None:
            raise ValueError("At least one of refs, locs, or labels must be provided.")
        locs = locs or []
        if refs is not None:
            for item in refs:
                locator = desktop.ref_store.resolve(RefStore.parse_ref(item))
                locs.append(list(desktop._locator_center(locator)))
        if labels is not None:
            if desktop.desktop_state is None:
                raise ValueError("Desktop state is empty. Please call Snapshot first.")
            try:
                resolved_locs = desktop.get_coordinates_from_labels(labels)
                locs.extend([list(loc) for loc in resolved_locs])
            except Exception as e:
                raise ValueError(f"Failed to resolve labels {labels}: {e}")

        for item in locs:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in item)
            ):
                raise ValueError(f"Each locs item must be [x, y] numbers. Invalid: {item!r}")

        press_ctrl = press_ctrl is True or (
            isinstance(press_ctrl, str) and press_ctrl.lower() == "true"
        )
        desktop.multi_select(press_ctrl, locs)
        elements_str = "\n".join([f"({loc[0]},{loc[1]})" for loc in locs])
        return f"Multi-selected elements at:\n{elements_str}"

    @mcp.tool(
        name="MultiEdit",
        description=(
            "Enters text into multiple input fields in one call. Target each field by "
            "refs=[[ref,text], ...] (@eN refs from Snapshot — preferred: resolves live "
            "elements, survives relayout, uses UIA ValuePattern when available), "
            "labels=[[label,text], ...] (numeric snapshot ids), or locs=[[x,y,text], ...] "
            "(raw coordinates). At least one of refs/labels/locs is required; they may "
            "be combined. Returns per-field results including method (setvalue/synthetic) "
            "and observed value changes."
        ),
        annotations=ToolAnnotations(
            title="MultiEdit",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics, "Multi-Edit-Tool")
    def multi_edit_tool(
        locs: list[list] | str | None = None,
        labels: list[list] | str | None = None,
        refs: list[list] | str | None = None,
        ctx: Context = None,
    ) -> str:
        desktop = get_desktop()
        locs = _as_loc(locs)
        labels = _as_loc(labels)
        refs = _as_loc(refs)
        if locs is None and labels is None and refs is None:
            raise ValueError("At least one of refs, labels, or locs must be provided.")

        # Each entry: (locator_or_None, x, y, text, via)
        fields: list[tuple[object, int, int, str, str]] = []

        if refs is not None:
            for item in refs:
                if len(item) != 2:
                    raise ValueError(f"Each refs item must be [ref, text]. Invalid: {item}")
                locator = desktop.ref_store.resolve(RefStore.parse_ref(item[0]))
                x, y = desktop._locator_center(locator)
                via = f"@e{locator.ref} ({locator.control_type} {locator.name!r})"
                fields.append((locator, x, y, str(item[1]), via))

        if labels is not None:
            if desktop.desktop_state is None:
                raise ValueError("Desktop state is empty. Please call Snapshot first.")
            # fields-index → (label_id) entries needing bulk coordinate fallback
            unresolved: list[tuple[int, int]] = []
            for item in labels:
                if len(item) != 2:
                    raise ValueError(f"Each label item must be [label, text]. Invalid: {item}")
                try:
                    label_id = int(item[0])
                except (ValueError, TypeError):
                    raise ValueError(f"Invalid label id in item: {item}")
                locator = desktop.resolve_label_locator(label_id)
                if isinstance(locator, ElementLocator):
                    x, y = desktop._locator_center(locator)
                    via = f"label {label_id} -> @e{locator.ref} ({locator.control_type} {locator.name!r})"
                    fields.append((locator, x, y, str(item[1]), via))
                else:
                    fields.append((None, 0, 0, str(item[1]), f"label {label_id}"))
                    unresolved.append((len(fields) - 1, label_id))
            if unresolved:
                label_ids = [u[1] for u in unresolved]
                resolved = desktop.get_coordinates_from_labels(label_ids)
                for (idx, label_id), (x, y) in zip(unresolved, resolved):
                    _, _, _, text, via = fields[idx]
                    fields[idx] = (None, x, y, text, via)

        for item in locs or []:
            if len(item) != 3:
                raise ValueError(f"Each locs item must be [x, y, text]. Invalid: {item}")
            fields.append((None, int(item[0]), int(item[1]), str(item[2]), f"({item[0]},{item[1]})"))

        results = []
        failures = []
        for locator, x, y, text, via in fields:
            try:
                if locator is not None:
                    result = actions.fill_value(locator, text)
                    if result is not None:
                        observed = actions.format_observed(result["changes"], result["after"])
                        results.append(f"{via}: setvalue -> {text!r}.{observed}")
                        continue
                desktop.type((x, y), text=text, clear=True)
                results.append(f"{via}: typed {text!r} (synthetic)")
            except Exception as e:
                failures.append(f"{via}: FAILED ({e})")
                results.append(f"{via}: FAILED ({e})")

        summary = f"Multi-edited {len(results) - len(failures)}/{len(results)} field(s)."
        if failures:
            summary += f" Failures: {'; '.join(failures)}"
        return summary + "\n" + "\n".join(f"  - {r}" for r in results)
