/** Mirrors backend PluginMeta / SkillMeta serialized by _meta_to_dict(). */
export interface EntryMeta {
  name: string;
  version: string;
  category: "input" | "process" | "output";
  is_dangerous: boolean;
  description: string;
}

/** POST /api/chat request body. */
export interface ChatRequest {
  message: string;
  history: ChatMessage[];
  context_paths?: string[];
}

/** POST /api/chat response. */
export interface ChatResponse {
  response: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/** GET /api/config response — api keys excluded. */
export interface RuntimeConfig {
  llm_model: string;
  llm_api_base: string | null;
  safe_mode: boolean;
  embedding_model: string;
  embedding_api_base: string | null;
  [key: string]: unknown;
}

/** PATCH /api/config request body. */
export interface ConfigUpdate {
  llm_model?: string;
  llm_api_key?: string;
  llm_api_base?: string | null;
  safe_mode?: boolean;
}

/** WebSocket event broadcast from EventBus. */
export interface WSEvent {
  type: "event";
  event_type: string;
  timestamp: string;
  correlation_id: string;
  payload: Record<string, unknown>;
}

/** WebSocket approval request (incoming). */
export interface ApprovalRequest {
  type: "approval_request";
  request_id: string;
  skill_name: string;
  description: string;
  action_summary: string;
}

/** WebSocket approval response (outgoing). */
export interface ApprovalResponse {
  type: "approval_response";
  request_id: string;
  approved: boolean;
}

/** Any message coming from the WebSocket. */
export type WSMessage = WSEvent | ApprovalRequest | { type: string; [key: string]: unknown };
