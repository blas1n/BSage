"""Maturity promoter — evaluate and promote garden note maturity."""

from bsage.plugin import plugin


@plugin(
    name="maturity-promoter",
    version="1.0.0",
    category="process",
    description="Evaluate garden notes and promote maturity based on graph connectivity and age",
    trigger={"type": "cron", "schedule": "0 6 * * *"},
)
async def execute(context) -> dict:
    """Scan all garden notes and promote eligible ones based on graph metrics."""
    result = await context.garden.promote_maturity(context.graph)
    if result["promoted"] > 0:
        details = ", ".join(
            f"{d['path']} ({d['from']}→{d['to']})" for d in result["details"]
        )
        await context.garden.write_action(
            "maturity-promoter",
            f"Promoted {result['promoted']} notes: {details}",
        )
    return result
