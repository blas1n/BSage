"""canon-lint — discoverability shim (Handoff §15.3).

The actual orphan-tag / alias-collision / redirect-anomaly detector
runs via the core scheduler in ``AppState.initialize`` on the
``RuntimeConfig.canon_lint_cron`` schedule when
``RuntimeConfig.canon_lint_enabled`` is ``True``. Wiring through the
core scheduler (rather than the Plugin pipeline) is intentional —
``CanonicalizationIndex`` + ``NoteStore`` live inside ``AppState`` and
aren't reachable from the restricted Plugin context.

This file exists so ``bsage plugins list`` shows the canon-lint slot.
For an interactive report, use ``bsage canon lint``.
"""

from bsage.plugin import plugin


@plugin(
    name="canon-lint",
    version="1.0.0",
    category="process",
    description=(
        "Detect orphan garden tags, alias collisions, and redirect anomalies. "
        "Real implementation is core-side; toggle via "
        "RuntimeConfig.canon_lint_enabled."
    ),
    trigger={"type": "on_demand"},
)
async def execute(context) -> dict:
    return {
        "status": "noop",
        "note": (
            "canon-lint runs via the core scheduler. Set "
            "runtime_config.canon_lint_enabled = True to enable, or run "
            "`bsage canon lint` for an interactive report."
        ),
    }
