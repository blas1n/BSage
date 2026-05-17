/** Event type display labels and colors. */
export const EVENT_COLORS: Record<string, string> = {
  plugin_run_start: "bg-secondary",
  plugin_run_complete: "bg-secondary-container",
  plugin_run_error: "bg-error",
  skill_run_start: "bg-accent-light",
  skill_gather_complete: "bg-accent-light",
  skill_llm_response: "bg-accent",
  skill_apply_complete: "bg-accent-dark",
  skill_run_complete: "bg-accent-dark",
  skill_run_error: "bg-error",
  seed_written: "bg-tertiary",
  garden_written: "bg-tertiary-container",
  action_logged: "bg-gray-600",
  trigger_fired: "bg-[#a78bfa]",
  tool_call_start: "bg-secondary",
  tool_call_complete: "bg-secondary-container",
  input_received: "bg-secondary",
  input_complete: "bg-secondary-container",
};

/** Maps backend event types to their `events.label.*` i18n keys. Module-level
 * (no hooks); translated at the render site. */
export const EVENT_LABEL_KEYS: Record<string, string> = {
  plugin_run_start: "events.label.pluginRunStart",
  plugin_run_complete: "events.label.pluginRunComplete",
  plugin_run_error: "events.label.pluginRunError",
  skill_run_start: "events.label.skillRunStart",
  skill_gather_complete: "events.label.skillGatherComplete",
  skill_llm_response: "events.label.skillLlmResponse",
  skill_apply_complete: "events.label.skillApplyComplete",
  skill_run_complete: "events.label.skillRunComplete",
  skill_run_error: "events.label.skillRunError",
  seed_written: "events.label.seedWritten",
  garden_written: "events.label.gardenWritten",
  action_logged: "events.label.actionLogged",
  trigger_fired: "events.label.triggerFired",
  tool_call_start: "events.label.toolCallStart",
  tool_call_complete: "events.label.toolCallComplete",
  input_received: "events.label.inputReceived",
  input_complete: "events.label.inputComplete",
};

export const CATEGORY_COLORS: Record<string, string> = {
  input: "bg-secondary-container/10 text-secondary",
  process: "bg-accent-light/10 text-accent-light",
  output: "bg-tertiary-container/10 text-tertiary",
};
