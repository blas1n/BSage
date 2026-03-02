/** Event type display labels and colors. */
export const EVENT_COLORS: Record<string, string> = {
  plugin_run_start: "bg-blue-500",
  plugin_run_complete: "bg-blue-600",
  plugin_run_error: "bg-red-500",
  skill_run_start: "bg-green-500",
  skill_gather_complete: "bg-green-400",
  skill_llm_response: "bg-green-500",
  skill_apply_complete: "bg-green-600",
  skill_run_complete: "bg-green-700",
  skill_run_error: "bg-red-500",
  seed_written: "bg-amber-500",
  garden_written: "bg-amber-600",
  action_logged: "bg-gray-500",
  trigger_fired: "bg-purple-500",
  tool_call_start: "bg-cyan-500",
  tool_call_complete: "bg-cyan-600",
  input_received: "bg-indigo-500",
  input_complete: "bg-indigo-600",
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
  input: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  process: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  output: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
};
