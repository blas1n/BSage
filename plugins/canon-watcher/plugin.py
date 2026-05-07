"""canon-watcher — discoverability shim (Handoff §15.3).

The actual filesystem observer lives in ``bsage.garden.canonicalization.watcher``
and is started by ``AppState.initialize`` when
``RuntimeConfig.canon_watcher_enabled`` is ``True``. A long-lived
watchdog Observer is fundamentally a daemon, not a one-shot
``execute(context)`` Plugin, so this file is intentionally a marker:
it exists so ``bsage plugins list`` shows the canon-watcher slot, and
operators know to flip the runtime flag (PATCH /api/config).
"""

from bsage.plugin import plugin


@plugin(
    name="canon-watcher",
    version="1.0.0",
    category="input",
    description=(
        "Filesystem watcher for canon-rooted vault edits. Real implementation "
        "is core-side; toggle via RuntimeConfig.canon_watcher_enabled."
    ),
    trigger={"type": "on_demand"},
)
async def execute(context) -> dict:
    return {
        "status": "noop",
        "note": (
            "canon-watcher is a core-side daemon. Set "
            "runtime_config.canon_watcher_enabled = True to start it."
        ),
    }
