"""canon-expire — discoverability shim (Handoff §15.3).

The actual stale-action / stale-proposal sweep is wired directly into
the BSage scheduler in ``AppState.initialize`` and runs on
``RuntimeConfig.canon_expire_cron`` when
``RuntimeConfig.canon_expire_enabled`` is ``True``. Wiring through the
core scheduler (rather than the Plugin pipeline) is intentional —
``CanonicalizationService`` lives inside ``AppState`` and isn't reachable
from the restricted Plugin context.

This file exists so ``bsage plugins list`` shows the canon-expire slot.
For an interactive sweep, use ``bsage canon expire``.
"""

from bsage.plugin import plugin


@plugin(
    name="canon-expire",
    version="1.0.0",
    category="process",
    description=(
        "Expire stale draft/pending actions and proposals. Real implementation "
        "is core-side; toggle via RuntimeConfig.canon_expire_enabled."
    ),
    trigger={"type": "on_demand"},
)
async def execute(context) -> dict:
    return {
        "status": "noop",
        "note": (
            "canon-expire runs via the core scheduler. Set "
            "runtime_config.canon_expire_enabled = True to enable, or run "
            "`bsage canon expire` for an interactive sweep."
        ),
    }
