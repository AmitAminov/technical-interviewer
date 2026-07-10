/**
 * Typed WebSocket client for /ws/interview/{session_id} (DESIGN.md §4, §11).
 *
 * Reliability contract:
 *  - outbound messages are queued while the socket is connecting and flushed
 *    once it opens;
 *  - on every successful open the client sends {"type":"start"} so the server
 *    begins (or resumes) delivery from its persisted session state;
 *  - on unexpected close it reconnects up to 3 times with exponential backoff
 *    (500ms / 1s / 2s) before reporting `failed`.
 */
import type { ClientMessage, ServerMessage, WsStatus } from './types';

const MAX_RECONNECTS = 3;
const BASE_BACKOFF_MS = 500;

export interface InterviewSocketHandlers {
  onMessage: (message: ServerMessage) => void;
  onStatus?: (status: WsStatus) => void;
}

export class InterviewSocket {
  private ws: WebSocket | null = null;
  private queue: string[] = [];
  private attempts = 0;
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private status: WsStatus = 'idle';

  constructor(
    private readonly sessionId: string,
    private readonly handlers: InterviewSocketHandlers,
  ) {}

  get currentStatus(): WsStatus {
    return this.status;
  }

  private setStatus(status: WsStatus): void {
    this.status = status;
    this.handlers.onStatus?.(status);
  }

  private url(): string {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}/ws/interview/${this.sessionId}`;
  }

  connect(): void {
    if (this.closedByUser) return;
    this.setStatus(this.attempts === 0 ? 'connecting' : 'reconnecting');
    const ws = new WebSocket(this.url());
    this.ws = ws;

    ws.onopen = () => {
      this.attempts = 0;
      this.setStatus('open');
      // Begin/resume delivery, then flush anything queued while connecting.
      ws.send(JSON.stringify({ type: 'start' }));
      const pending = this.queue.splice(0, this.queue.length);
      for (const raw of pending) ws.send(raw);
    };

    ws.onmessage = (event: MessageEvent) => {
      let parsed: ServerMessage;
      try {
        parsed = JSON.parse(String(event.data)) as ServerMessage;
      } catch {
        return; // ignore malformed frames
      }
      if (parsed && typeof parsed === 'object' && 'type' in parsed) {
        this.handlers.onMessage(parsed);
      }
    };

    ws.onclose = () => {
      if (this.closedByUser) return;
      if (this.attempts < MAX_RECONNECTS) {
        this.attempts += 1;
        this.setStatus('reconnecting');
        const delay = BASE_BACKOFF_MS * 2 ** (this.attempts - 1);
        this.reconnectTimer = setTimeout(() => this.connect(), delay);
      } else {
        this.setStatus('failed');
      }
    };

    ws.onerror = () => {
      /* onclose always follows an error; reconnect logic lives there */
    };
  }

  /** Send a message now, or queue it until the socket (re)opens. */
  send(message: ClientMessage): void {
    const raw = JSON.stringify(message);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(raw);
    } else if (!this.closedByUser) {
      this.queue.push(raw);
    }
  }

  /** Permanently close the socket (no reconnect). */
  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    try {
      this.ws?.close();
    } catch {
      /* already closed */
    }
    this.setStatus('closed');
  }
}
