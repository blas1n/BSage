"""BSNexus input Plugin — receives deliverable payloads from BSNexus runs.

BSNexus's RunOrchestrator POSTs a JSON body to
``POST /api/webhooks/bsnexus-input`` each time an ExecutionRun publishes
output. The plugin writes the payload as a raw seed — no pre-computed
title — so that AgentLoop's seed-refiner LLM pass derives a concise
title (under 30 chars) from the actual run output.

This mirrors the pattern used by every other input plugin in BSage:
plugins collect raw data, the core refiner owns titling.
"""

from bsage.plugin import plugin


@plugin(
    name="bsnexus-input",
    version="1.0.0",
    category="input",
    description="Receive ExecutionRun deliverables from BSNexus as seeds",
    trigger={"type": "webhook"},
)
async def execute(context) -> dict:
    """Forward the webhook body to seeds/bsnexus/ for refinement."""
    webhook_data = context.input_data or {}
    if not webhook_data:
        return {"collected": 0}

    # Strip gateway-injected machinery before persisting. The refiner
    # only sees what BSNexus actually sent.
    seed = {k: v for k, v in webhook_data.items() if k not in {"raw_body", "x-hub-signature-256"}}
    if not seed:
        return {"collected": 0}

    await context.garden.write_seed("bsnexus", seed)
    return {"collected": 1}
