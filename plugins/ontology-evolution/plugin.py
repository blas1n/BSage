"""Ontology evolution — periodic schema review (DEPRECATE, MERGE candidates)."""

from bsage.plugin import plugin


@plugin(
    name="ontology-evolution",
    version="1.0.0",
    category="process",
    description="Periodically review ontology for DEPRECATE and MERGE candidates",
    trigger={"type": "cron", "schedule": "0 3 * * *"},
)
async def execute(context) -> dict:
    """Evaluate the ontology for evolution opportunities.

    Checks:
    1. DEPRECATE — entity types with zero new notes in N days
    2. Report candidates in action log (actual merge/split requires LLM judgment)
    """
    ontology = context.config.get("_ontology")
    if ontology is None:
        return {"status": "skipped", "reason": "no ontology available"}

    graph = context.graph
    if graph is None:
        return {"status": "skipped", "reason": "no graph available"}

    evo_config = ontology.get_evolution_config()
    deprecate_days = evo_config.get("deprecate_days", 90)

    candidates = []
    entity_types = ontology.get_entity_types()

    for type_name, type_info in entity_types.items():
        # Skip virtual types (tag, source) without folders
        if not type_info.get("folder"):
            continue

        # Check if type has any recent activity
        count = await graph.count_relationships_for_entity(type_name)
        if count == 0:
            candidates.append(
                {"type": type_name, "action": "deprecate_candidate", "reason": "no relationships"}
            )

    # Auto-deprecate types with zero activity
    deprecated = 0
    for candidate in candidates:
        result = await ontology.deprecate_entity_type(
            candidate["type"],
            reason=candidate["reason"],
        )
        if result:
            deprecated += 1

    if deprecated > 0 or candidates:
        summary_parts = []
        if deprecated:
            summary_parts.append(f"Deprecated {deprecated} types")
        if candidates:
            names = ", ".join(c["type"] for c in candidates)
            summary_parts.append(f"Candidates reviewed: {names}")
        await context.garden.write_action(
            "ontology-evolution",
            ". ".join(summary_parts),
        )

    return {
        "status": "completed",
        "candidates": len(candidates),
        "deprecated": deprecated,
    }
