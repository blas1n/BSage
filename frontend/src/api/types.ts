/** Mirrors backend PluginMeta / SkillMeta serialized by _meta_to_dict(). */
export interface EntryMeta {
  name: string;
  version: string;
  category: "input" | "process" | "output";
  is_dangerous: boolean;
  description: string;
  has_credentials: boolean;
  credentials_configured: boolean;
  enabled: boolean;
  trigger?: { type: string; schedule?: string; sources?: string[]; hint?: string } | null;
  entry_type: "plugin" | "skill";
  /** JSON Schema describing the input_data payload accepted by /api/run/{name}. */
  input_schema?: Record<string, unknown> | null;
  /** True when the plugin opts in to MCP tool registration. */
  mcp_exposed?: boolean;
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
  disabled_entries: string[];
  has_llm_api_key: boolean;
  index_available: boolean;
  /** Present only when embedding is configured. */
  embedding_model?: string;
  embedding_api_base?: string | null;
  has_embedding_api_key?: boolean;
  vault_path?: string;
}

/** PATCH /api/config request body. */
export interface ConfigUpdate {
  llm_model?: string;
  llm_api_key?: string;
  llm_api_base?: string | null;
  safe_mode?: boolean;
  disabled_entries?: string[];
}

/** GET /api/entries/{name}/credentials/fields response. */
export interface CredentialFieldsResponse {
  name: string;
  fields: CredentialField[];
}

export interface CredentialField {
  name: string;
  description: string;
  required: boolean;
}

/** GET /api/vault/tree response entry. */
export interface VaultTreeEntry {
  path: string;
  dirs: string[];
  files: string[];
}

/** GET /api/vault/file response. */
export interface VaultFileResponse {
  path: string;
  content: string;
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

/** GET /api/vault/search response entry. */
export interface VaultSearchResult {
  path: string;
  matches: { line: number; text: string }[];
}

/** GET /api/vault/backlinks response entry. */
export interface VaultBacklink {
  path: string;
  title: string;
}

/** GET /api/vault/graph response. */
export interface VaultGraph {
  nodes: VaultGraphNode[];
  links: VaultGraphLink[];
  truncated: boolean;
}

export interface VaultGraphNode {
  id: string;
  name: string;
  group: string;
}

export interface VaultGraphLink {
  source: string;
  target: string;
}

/** POST /api/config/test-llm response. */
export interface LlmTestResult {
  ok: boolean;
  model?: string;
  latency_ms?: number;
  reply?: string;
  error?: string;
  detail?: string;
  hint?: string;
}

/** GET /api/vault/communities response. */
export interface VaultCommunities {
  communities: VaultCommunity[];
  algorithm: string;
  total: number;
}

export interface VaultCommunity {
  id: number;
  label: string;
  size: number;
  cohesion: number;
  members: string[];
  color: string;
}

/** GET /api/vault/tags response. */
export interface VaultTags {
  tags: Record<string, string[]>;
  truncated: boolean;
}
