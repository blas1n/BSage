"""Built-in maintenance tasks — core scheduled jobs that must always run.

These are NOT plugins. They are infrastructure tasks that the system
depends on for correctness (maturity promotion/demotion, edge lifecycle,
ontology evolution). They run on fixed cron schedules via the Scheduler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.config import Settings
    from bsage.garden.graph_store import GraphStore
    from bsage.garden.ontology import OntologyRegistry
    from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)

# Schedule definitions: (name, cron, description)
MAINTENANCE_SCHEDULES: list[tuple[str, str]] = [
    ("maintenance:maturity", "0 6 * * *"),
    ("maintenance:edge-lifecycle", "0 4 * * *"),
    ("maintenance:ontology-evolution", "0 3 * * *"),
]


class MaintenanceTasks:
    """Core maintenance tasks that run on fixed schedules.

    Unlike plugins, these have direct access to internal modules
    and are guaranteed to run as long as the scheduler is active.
    """

    def __init__(
        self,
        garden_writer: GardenWriter,
        graph_store: GraphStore | None = None,
        ontology: OntologyRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._garden = garden_writer
        self._graph = graph_store
        self._ontology = ontology
        self._settings = settings

    async def run_maturity(self) -> dict[str, Any]:
        """Evaluate and promote/demote garden note maturity."""
        try:
            config = None
            if self._settings:
                from bsage.garden.maturity import MaturityConfig

                config = MaturityConfig(
                    seedling_min_relationships=self._settings.maturity_seedling_min_relationships,
                    budding_min_sources=self._settings.maturity_budding_min_sources,
                    evergreen_min_days_stable=self._settings.maturity_evergreen_min_days_stable,
                    evergreen_min_relationships=self._settings.maturity_evergreen_min_relationships,
                )
            result = await self._garden.promote_maturity(self._graph, config=config)
            if result["promoted"] > 0:
                details = ", ".join(
                    f"{d['path']} ({d['from']}→{d['to']})" for d in result["details"]
                )
                await self._garden.write_action(
                    "maintenance:maturity",
                    f"Promoted {result['promoted']} notes: {details}",
                )
            logger.info(
                "maintenance_maturity_done",
                promoted=result["promoted"],
                checked=result["checked"],
            )
            return result
        except Exception:
            logger.exception("maintenance_maturity_failed")
            return {"promoted": 0, "checked": 0, "details": [], "error": True}

    async def run_edge_lifecycle(self) -> dict[str, Any]:
        """Promote frequently-mentioned weak edges; demote stale strong edges."""
        if self._graph is None:
            return {"status": "skipped", "reason": "no graph"}

        try:
            from bsage.garden.edge_lifecycle import EdgeLifecycleConfig, EdgeLifecycleEvaluator

            edge_config = EdgeLifecycleConfig()
            if self._settings:
                edge_config = EdgeLifecycleConfig(
                    promotion_min_mentions=self._settings.edge_promotion_min_mentions,
                    demotion_days=self._settings.edge_decay_days,
                )
            evaluator = EdgeLifecycleEvaluator(self._graph, edge_config)
            promoted = await evaluator.promote_edges()
            demoted = await evaluator.demote_edges()

            if promoted or demoted:
                await self._garden.write_action(
                    "maintenance:edge-lifecycle",
                    f"Promoted {promoted} edges, demoted {demoted} edges",
                )
            logger.info(
                "maintenance_edge_lifecycle_done",
                promoted=promoted,
                demoted=demoted,
            )
            return {"promoted": promoted, "demoted": demoted}
        except Exception:
            logger.exception("maintenance_edge_lifecycle_failed")
            return {"promoted": 0, "demoted": 0, "error": True}

    async def run_ontology_evolution(self) -> dict[str, Any]:
        """Ontology evolution is a no-op since the dynamic-ontology refactor.

        Entity types went free-form, so the old "deprecate zero-activity
        types" loop has nothing to deprecate. Kept as a stable maintenance
        endpoint so existing schedules don't break — relation_types
        evolution is a future extension.
        """
        if self._ontology is None or self._graph is None:
            return {"status": "skipped", "reason": "no ontology or graph"}

        try:
            candidates: list[str] = []
            deprecated = 0
            logger.info(
                "maintenance_ontology_evolution_done",
                candidates=len(candidates),
                deprecated=deprecated,
            )
            return {"candidates": len(candidates), "deprecated": deprecated}
        except Exception:
            logger.exception("maintenance_ontology_evolution_failed")
            return {"candidates": 0, "deprecated": 0, "error": True}
