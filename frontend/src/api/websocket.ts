import type { ApprovalResponse, WSMessage } from "./types";

export type ConnectionState = "connected" | "disconnected" | "reconnecting";
export type MessageHandler = (msg: WSMessage) => void;
export type StateHandler = (state: ConnectionState) => void;

/**
 * WebSocket manager with auto-reconnect.
 * Singleton — call connect() once, subscribe from multiple components.
 */
class WebSocketManager {
  private ws: WebSocket | null = null;
  private messageHandlers = new Set<MessageHandler>();
  private stateHandlers = new Set<StateHandler>();
  private _state: ConnectionState = "disconnected";
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private url = "";
  private authToken?: string;

  get state() {
    return this._state;
  }

  connect(url: string, authToken?: string) {
    if (this.ws && this.url === url && this.authToken === authToken) return;
    this.disconnect();
    this.url = url;
    this.authToken = authToken;
    this._connect();
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
    this.setState("disconnected");
  }

  subscribe(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStateChange(handler: StateHandler): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  send(data: ApprovalResponse) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private _connect() {
    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      if (this.authToken) {
        this.ws?.send(JSON.stringify({ type: "auth", token: this.authToken }));
      }
      this.setState("connected");
    };

    this.ws.onmessage = (e) => {
      try {
        const msg: WSMessage = JSON.parse(e.data);
        if (msg.type === "ack") return;
        this.messageHandlers.forEach((h) => h(msg));
      } catch {
        // ignore parse errors
      }
    };

    this.ws.onclose = () => {
      this.setState("reconnecting");
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this._connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
  }

  private setState(s: ConnectionState) {
    this._state = s;
    this.stateHandlers.forEach((h) => h(s));
  }
}

export const wsManager = new WebSocketManager();
