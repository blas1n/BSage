"""Edge lifecycle — periodic promotion and demotion of graph edges."""

from bsage.plugin import plugin


@plugin(
    name="edge-lifecycle",
    version="1.0.0",
    category="process",
    description="Promote frequently-mentioned weak edges to strong; demote stale strong edges to weak",
    trigger={"type": "cron", "schedule": "0 4 * * *"},
)
async def execute(context) -> dict:
    """Run edge promotion and demotion cycle."""
    graph = context.graph
    if graph is None:
        return {"status": "skipped", "reason": "no graph available"}

    from bsage.garden.edge_lifecycle import EdgeLifecycleConfig, EdgeLifecycleEvaluator

    config = EdgeLifecycleConfig()
    evaluator = EdgeLifecycleEvaluator(graph, config)

    promoted = await evaluator.promote_edges()
    demoted = await evaluator.demote_edges()

    if promoted or demoted:
        await context.garden.write_action(
            "edge-lifecycle",
            f"Promoted {promoted} edges, demoted {demoted} edges",
        )

    return {"status": "completed", "promoted": promoted, "demoted": demoted}
