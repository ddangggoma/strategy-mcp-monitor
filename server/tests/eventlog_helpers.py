"""Builds Windows event XML in the shape ``EvtRender(EvtRenderEventXml)`` produces."""

from __future__ import annotations

from collections.abc import Mapping
from xml.sax.saxutils import escape, quoteattr

EVENT_NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def _data_element(name: str | None, value: str | None) -> str:
    attr = "" if name is None else f" Name={quoteattr(name)}"
    if value is None:
        return f"<Data{attr}/>"
    return f"<Data{attr}>{escape(value)}</Data>"


def evt_xml(
    channel: str,
    event_id: int,
    record_id: int,
    time: str = "2026-11-04T05:00:00.1234567Z",
    *,
    provider: str = "Microsoft-Windows-Security-Auditing",
    data: Mapping[str, str | None] | None = None,
    user_data: tuple[str, Mapping[str, str | None]] | None = None,
    pid: int = 4,
    user_sid: str | None = None,
) -> str:
    """One event as Windows renders it: the event namespace, the ``System`` children in Windows'
    order, then ``EventData`` (``data``) or ``UserData`` (``user_data`` = (element, children)).
    A ``None`` value renders as an empty element."""
    security = "<Security/>" if user_sid is None else f"<Security UserID={quoteattr(user_sid)}/>"
    system = (
        f"<System><Provider Name={quoteattr(provider)}/><EventID>{event_id}</EventID>"
        "<Version>0</Version><Level>0</Level><Task>0</Task><Opcode>0</Opcode>"
        "<Keywords>0x8020000000000000</Keywords>"
        f"<TimeCreated SystemTime={quoteattr(time)}/><EventRecordID>{record_id}</EventRecordID>"
        f"<Correlation/><Execution ProcessID='{pid}' ThreadID='{pid + 100}'/>"
        f"<Channel>{escape(channel)}</Channel><Computer>MCP-HOST</Computer>{security}</System>"
    )
    if user_data is not None:
        element, children = user_data
        inner = "".join(
            f"<{k}/>" if v is None else f"<{k}>{escape(v)}</{k}>" for k, v in children.items()
        )
        body = f"<UserData><{element} xmlns='Event_NS'>{inner}</{element}></UserData>"
    else:
        body = "<EventData>" + "".join(
            _data_element(k, v) for k, v in (data or {}).items()
        ) + "</EventData>"
    return f"<Event xmlns='{EVENT_NS}'>{system}{body}</Event>"
