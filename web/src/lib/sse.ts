// Incremental text/event-stream parser (WHATWG HTML "Server-sent events" §9.2.6, minus id/retry,
// which the board stream never sends). Fed decoded text chunks of any size: events, lines and even
// a CRLF pair may be split across chunks. The fetch-based stream client uses it instead of
// EventSource because it needs status codes and heartbeat comments (U4).

export interface SseEvent {
  event: string;
  data: string;
}

export function createSseParser(
  onEvent: (e: SseEvent) => void,
  onComment?: () => void,
): (chunk: string) => void {
  let buffer = "";
  let skipLf = false; // the previous chunk ended in "\r": a leading "\n" belongs to that line end
  let eventName = "";
  let data: string[] = [];

  function line(text: string): void {
    if (text === "") {
      if (data.length > 0) onEvent({ event: eventName || "message", data: data.join("\n") });
      eventName = "";
      data = [];
      return;
    }
    if (text.startsWith(":")) {
      onComment?.();
      return;
    }
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") eventName = value;
    else if (field === "data") data.push(value);
    // id, retry and unknown fields are ignored
  }

  return (chunk) => {
    buffer += chunk;
    let start = 0;
    if (skipLf && buffer.startsWith("\n")) start = 1;
    skipLf = false;
    for (let i = start; i < buffer.length; i++) {
      const c = buffer[i];
      if (c !== "\n" && c !== "\r") continue;
      line(buffer.slice(start, i));
      if (c === "\r") {
        if (i + 1 === buffer.length) skipLf = true;
        else if (buffer[i + 1] === "\n") i++;
      }
      start = i + 1;
    }
    buffer = buffer.slice(start);
  };
}
