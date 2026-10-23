/**
 * Incremental parser for `text/event-stream` (WHATWG HTML §9.2.6). Feed it decoded text chunks
 * in any split; it returns the messages completed by each chunk.
 */
export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
  retry: number | null;
}

export class SseParser {
  private buffer = "";
  private data: string[] = [];
  private event = "";
  private id: string | null = null;
  private retry: number | null = null;

  push(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const messages: SseMessage[] = [];
    // A trailing "\r" may be the first half of "\r\n", so keep it until more text arrives.
    const lines = this.buffer.split(/\r\n|\r(?!$)|\n/);
    this.buffer = lines.pop() ?? "";
    for (const line of lines) {
      const message = this.line(line);
      if (message) messages.push(message);
    }
    return messages;
  }

  private line(line: string): SseMessage | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "data":
        this.data.push(value);
        break;
      case "event":
        this.event = value;
        break;
      case "id":
        if (!value.includes("\0")) this.id = value;
        break;
      case "retry":
        if (/^\d+$/.test(value)) this.retry = Number(value);
        break;
    }
    return null;
  }

  private dispatch(): SseMessage | null {
    const retry = this.retry;
    this.retry = null;
    if (this.data.length === 0) {
      this.event = "";
      return retry === null ? null : { id: this.id, event: "", data: "", retry };
    }
    const message: SseMessage = {
      id: this.id,
      event: this.event || "message",
      data: this.data.join("\n"),
      retry,
    };
    this.data = [];
    this.event = "";
    return message;
  }
}
