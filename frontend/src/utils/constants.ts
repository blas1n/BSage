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

export const EVENT_LABELS: Record<string, string> = {
  plugin_run_start: "Plugin Start",
  plugin_run_complete: "Plugin Done",
  plugin_run_error: "Plugin Error",
  skill_run_start: "Skill Start",
  skill_gather_complete: "Skill Gather",
  skill_llm_response: "Skill LLM",
  skill_apply_complete: "Skill Apply",
  skill_run_complete: "Skill Done",
  skill_run_error: "Skill Error",
  seed_written: "Seed Written",
  garden_written: "Garden Written",
  action_logged: "Action Logged",
  trigger_fired: "Trigger Fired",
  tool_call_start: "Tool Start",
  tool_call_complete: "Tool Done",
  input_received: "Input Received",
  input_complete: "Input Complete",
};

export const CATEGORY_COLORS: Record<string, string> = {
  input: "bg-secondary-container/10 text-secondary",
  process: "bg-accent-light/10 text-accent-light",
  output: "bg-tertiary-container/10 text-tertiary",
};
