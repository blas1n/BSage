import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { forceCollide, forceX, forceY } from "d3-force";
import ReactMarkdown from "react-markdown";
import { useTranslation } from "react-i18next";
import remarkGfm from "remark-gfm";
import remarkObsidian from "@thecae/remark-obsidian";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkWikiLink from "../../lib/remarkWikiLink";
import {
  buildNodeCommunityIdMap,
  computeCommunityCentroids,
  computeDegree,
  labelDegreeThreshold,
  labelHalfWidth,
  nodeRadius,
  shouldShowLabel,
} from "../../lib/graphPhysics";
import { api } from "../../api/client";
import type { VaultGraph, VaultGraphNode, VaultBacklink, VaultCommunity } from "../../api/types";
import { Icon } from "../common/Icon";

// Palette applied in deterministic order to whatever groups show up in the
// graph response. New ontology entity types land on a fresh slot without any
// frontend change.
const GROUP_PALETTE = [
  "#4edea3", "#adc6ff", "#ffb95f", "#ff7eb3", "#7ec8e3",
  "#c4b5fd", "#fca5a5", "#86efac", "#fde68a", "#a5b4fc",
  "#f0abfc", "#67e8f9", "#fdba74", "#d9f99d", "#cbd5e1",
];
const FALLBACK_COLOR = "#a78bfa";

// Optional icon hints for known structural groups; unknown groups get folder_open.
const GROUP_ICON_HINTS: Record<string, string> = {
  seeds: "psychology",
  actions: "bolt",
  garden: "local_florist",
  _index: "list",
  people: "person",
  projects: "work",
  ideas: "lightbulb",
  insights: "auto_awesome",
  events: "event",
  tasks: "check_circle",
  facts: "fact_check",
  preferences: "favorite",
};

function humanizeGroup(group: string): string {
  if (!group) return "Other";
  const cleaned = group.replace(/^_/, "").replace(/[-_]/g, " ");
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/** Split YAML frontmatter from markdown body. */
function splitFrontmatter(text: string): {
  meta: { key: string; value: string }[];
  body: string;
} {
  if (!text.startsWith("---\n")) return { meta: [], body: text };
  const endIdx = text.indexOf("\n---\n", 4);
  if (endIdx === -1) return { meta: [], body: text };

  const yamlBlock = text.slice(4, endIdx);
  const body = text.slice(endIdx + 5);

  const entries: { key: string; value: string }[] = [];
  for (const line of yamlBlock.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const colonIdx = trimmed.indexOf(":");
    if (colonIdx === -1) continue;
    const key = trimmed.slice(0, colonIdx).trim();
    let val = trimmed.slice(colonIdx + 1).trim();
    if (
      (val.startsWith("'") && val.endsWith("'")) ||
      (val.startsWith('"') && val.endsWith('"'))
    ) {
      val = val.slice(1, -1);
    }
    entries.push({ key, value: val });
  }
  return { meta: entries, body };
}

export function KnowledgeGraphView() {
  const { t } = useTranslation();
  const [graphData, setGraphData] = useState<VaultGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  // `null` = no filter applied (all groups visible). When the user toggles
  // one off, the set becomes the explicit allowlist.
  const [activeFilters, setActiveFilters] = useState<Set<string> | null>(null);
  const [selectedNode, setSelectedNode] = useState<VaultGraphNode | null>(null);
  const [noteContent, setNoteContent] = useState<string | null>(null);
  const [noteLoading, setNoteLoading] = useState(false);
  const [backlinks, setBacklinks] = useState<VaultBacklink[]>([]);
  const [communities, setCommunities] = useState<VaultCommunity[]>([]);
  // Step B4 of the dynamic-ontology refactor: identity in this graph
  // comes from connections (Louvain communities), not folder labels —
  // default to community coloring so users see the emergent structure
  // first. Group mode is still selectable for users who want the
  // file-system-shape view.
  const [colorMode, setColorMode] = useState<"group" | "community">("community");
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<unknown>(null);
  const labelWidthCacheRef = useRef<Map<string, number>>(new Map());
  const [dimensions, setDimensions] = useState<{
    width: number;
    height: number;
  } | null>(null);

  useEffect(() => {
    api
      .vaultGraph()
      .then(setGraphData)
      .catch(() => setGraphData({ nodes: [], links: [], truncated: false }))
      .finally(() => setLoading(false));
    api
      .vaultCommunities()
      .then((res) => setCommunities(res.communities))
      .catch(() => setCommunities([]));
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setDimensions({ width: el.clientWidth, height: el.clientHeight });
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Compute legend entries from actual graph data: each unique group gets
  // a color (icon hinted when known) and node count. Palette cycles.
  const groupsInfo = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of graphData?.nodes ?? []) {
      counts[n.group] = (counts[n.group] ?? 0) + 1;
    }
    return Object.entries(counts)
      .sort(([, a], [, b]) => b - a)
      .map(([group, count], idx) => ({
        group,
        count,
        label: humanizeGroup(group),
        color: GROUP_PALETTE[idx % GROUP_PALETTE.length],
        icon: GROUP_ICON_HINTS[group] ?? "folder_open",
      }));
  }, [graphData]);

  const groupColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const g of groupsInfo) map[g.group] = g.color;
    return map;
  }, [groupsInfo]);

  const toggleFilter = useCallback((group: string) => {
    setActiveFilters((prev) => {
      // First click initializes the allowlist to every known group, then
      // toggles this one off. Subsequent clicks toggle individual groups.
      const base = prev ?? new Set(groupsInfo.map((g) => g.group));
      const next = new Set(base);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  }, [groupsInfo]);

  // Build node -> community color lookup
  const communityColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of communities) {
      for (const memberId of c.members) {
        map[memberId] = c.color;
      }
    }
    return map;
  }, [communities]);

  // Build node id -> community lookup for sidebar
  const nodeCommunityMap = useMemo(() => {
    const map: Record<string, VaultCommunity> = {};
    for (const c of communities) {
      for (const memberId of c.members) {
        map[memberId] = c;
      }
    }
    return map;
  }, [communities]);

  const filteredData = useMemo(() => {
    if (!graphData) return null;
    const query = searchQuery.toLowerCase();
    const nodes = graphData.nodes.filter((n) => {
      if (activeFilters && !activeFilters.has(n.group)) return false;
      if (query && !n.name.toLowerCase().includes(query)) return false;
      return true;
    });
    const nodeIds = new Set(nodes.map((n) => n.id));
    const links = graphData.links.filter(
      (l) => nodeIds.has(l.source as string) && nodeIds.has(l.target as string),
    );
    return {
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    };
  }, [graphData, activeFilters, searchQuery]);

  // Degree map + LOD threshold derived once per filter change.
  const degreeMap = useMemo(
    () => computeDegree(filteredData?.links ?? []),
    [filteredData],
  );
  const hubThreshold = useMemo(
    () => labelDegreeThreshold(degreeMap, 0.05),
    [degreeMap],
  );
  const nodeCommunityIdMap = useMemo(
    () => buildNodeCommunityIdMap(communities),
    [communities],
  );

  // Wire custom d3 forces once the simulation is mounted. Re-runs whenever
  // the underlying data changes so collide radii reflect new degrees.
  useEffect(() => {
    const fg = fgRef.current as
      | {
          d3Force: (
            name: string,
            force?: unknown,
          ) => unknown;
        }
      | null;
    if (!fg || !filteredData) return;

    // Modify built-in forces in place — react-force-graph creates default
    // 'charge' and 'link' forces internally. Replacing them entirely (esp.
    // the link force) breaks its internal id-resolution and the canvas
    // never paints. Only mutate properties.
    const charge = fg.d3Force("charge") as
      | { strength: (s: number) => unknown; theta?: (t: number) => unknown }
      | undefined;
    if (charge) {
      charge.strength(-160);
      charge.theta?.(0.9);
    }
    const linkForce = fg.d3Force("link") as
      | { distance: (d: number) => unknown; strength: (s: number) => unknown }
      | undefined;
    if (linkForce) {
      linkForce.distance(40);
      linkForce.strength(0.4);
    }
    fg.d3Force(
      "collide",
      forceCollide()
        .radius((d) => {
          const id = (d as unknown as { id?: string }).id;
          const deg = (id && degreeMap[id]) || 0;
          return nodeRadius(deg, false) + 8;
        })
        .iterations(1),
    );
    // Weak centering to keep isolated / low-degree nodes inside the canvas.
    // Without this, charge=-160 pushes degree-0 nodes off-screen and the
    // user has to drag the canvas to find them.
    fg.d3Force("x", forceX(0).strength(0.05));
    fg.d3Force("y", forceY(0).strength(0.05));

    // Custom 'cluster' force: pull each node toward its community centroid.
    const clusterForce = (alpha: number) => {
      if (communities.length === 0 || !filteredData) return;
      const centroids = computeCommunityCentroids(filteredData.nodes, communities);
      const strength = 0.05 * alpha;
      for (const n of filteredData.nodes as Array<{
        id: string;
        x?: number;
        y?: number;
        vx?: number;
        vy?: number;
      }>) {
        const cid = nodeCommunityIdMap.get(n.id);
        if (cid === undefined) continue;
        const c = centroids.get(cid);
        if (!c || n.x === undefined || n.y === undefined) continue;
        n.vx = (n.vx ?? 0) + (c.x - n.x) * strength;
        n.vy = (n.vy ?? 0) + (c.y - n.y) * strength;
      }
    };
    fg.d3Force("cluster", clusterForce);
  }, [filteredData, degreeMap, communities, nodeCommunityIdMap]);

  const handleNodeClick = useCallback(async (node: { id?: string; name?: string; group?: string }) => {
    if (process.env.NODE_ENV !== "production") {
      console.debug("graph_node_click", { id: node.id, name: node.name, group: node.group });
    }
    if (!node.id) return;
    const id = node.id as string;
    setSelectedNode({ id, name: node.name || id, group: node.group || "root" });
    setNoteLoading(true);
    setNoteContent(null);
    const [fileRes, blRes] = await Promise.allSettled([
      api.vaultFile(id),
      api.vaultBacklinks(id),
    ]);
    setNoteContent(fileRes.status === "fulfilled" ? fileRes.value.content : null);
    setBacklinks(blRes.status === "fulfilled" ? blRes.value : []);
    setNoteLoading(false);
  }, []);

  const nodeCanvasObject = useCallback(
    (
      rawNode: { x?: number; y?: number; id?: string; name?: string; group?: string },
      ctx: CanvasRenderingContext2D,
      globalScale: number,
    ) => {
      const x = rawNode.x ?? 0;
      const y = rawNode.y ?? 0;
      const group = rawNode.group ?? "";
      const label = rawNode.name || "";
      const fontSize = Math.max(12 / globalScale, 3);
      const nodeColor =
        colorMode === "community" && rawNode.id && communityColorMap[rawNode.id as string]
          ? communityColorMap[rawNode.id as string]
          : groupColorMap[group] ?? FALLBACK_COLOR;
      const isSelected = selectedNode?.id === rawNode.id;
      const degree = (rawNode.id && degreeMap[rawNode.id]) || 0;
      const radius = nodeRadius(degree, isSelected);

      // Glow for selected node
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, radius + 10, 0, 2 * Math.PI);
        const gradient = ctx.createRadialGradient(x, y, radius, x, y, radius + 10);
        gradient.addColorStop(0, nodeColor + "40");
        gradient.addColorStop(1, nodeColor + "00");
        ctx.fillStyle = gradient;
        ctx.fill();

        // Dashed orbit ring
        ctx.beginPath();
        ctx.arc(x, y, radius + 6, 0, 2 * Math.PI);
        ctx.strokeStyle = nodeColor + "60";
        ctx.lineWidth = 1 / globalScale;
        ctx.setLineDash([4 / globalScale, 2 / globalScale]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Subtle glow for garden nodes
      if (group === "garden" && !isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, radius + 3, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(78, 222, 163, 0.12)";
        ctx.fill();
      }

      // Node circle
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = nodeColor;
      ctx.fill();

      // Selection ring
      if (isSelected) {
        ctx.strokeStyle = "#f2f3f7";
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      // LOD label — only render when zoomed in OR for hub nodes/selected.
      if (!isSelected && !shouldShowLabel(globalScale, degree, hubThreshold)) {
        return;
      }
      // Warm the label-width cache so collide force has consistent sizing.
      labelHalfWidth(label, ctx, labelWidthCacheRef.current, fontSize);
      ctx.font = `${fontSize}px "Plus Jakarta Sans", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = isSelected ? "#f2f3f7" : "#86948a";
      ctx.fillText(label, x, y + radius + 2);
    },
    [selectedNode, colorMode, communityColorMap, groupColorMap, degreeMap, hubThreshold],
  );

  const parsed = useMemo(() => {
    if (!noteContent) return null;
    return splitFrontmatter(noteContent);
  }, [noteContent]);

  const sanitizeSchema = useMemo(
    () => ({
      ...defaultSchema,
      attributes: {
        ...defaultSchema.attributes,
        "*": [...(defaultSchema.attributes?.["*"] || []), "className"],
      },
    }),
    [],
  );

  const showGraph =
    !loading && filteredData && filteredData.nodes.length > 0 && dimensions;

  return (
    <div className="flex h-full relative">
      {/* Main graph area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar: search + filters */}
        <div className="shrink-0 px-6 py-3 border-b border-white/5 flex items-center gap-4">
          <div className="relative flex-1 max-w-sm">
            <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("graph.searchPlaceholder")}
              className="min-h-10 w-full pl-10 pr-8 py-1.5 rounded-lg border-b-2 border-transparent bg-surface-container-low text-sm text-on-surface outline-none focus:border-accent-light placeholder:text-gray-500 font-sans"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-1 top-1/2 inline-flex min-h-10 min-w-10 -translate-y-1/2 items-center justify-center rounded-lg text-gray-500 hover:bg-white/5 hover:text-gray-300"
              >
                <Icon name="close" size={16} />
              </button>
            )}
          </div>

          {activeFilters && (
            <button
              onClick={() => setActiveFilters(null)}
              className="min-h-10 text-[10px] font-mono uppercase tracking-widest text-gray-500 hover:text-accent-light transition-colors"
            >
              {t("graph.showAll")}
            </button>
          )}
        </div>

        {/* Graph canvas */}
        <div ref={containerRef} className="flex-1 min-h-0 relative bg-surface-dim">
          {loading && (
            <div className="flex items-center justify-center h-full text-gray-500">
              {t("graph.loading")}
            </div>
          )}
          {!loading &&
            (!filteredData || filteredData.nodes.length === 0) && (
              <div className="flex items-center justify-center h-full text-gray-500">
                <div className="text-center">
                  <Icon name="folder_open" className="mx-auto mb-2 opacity-50" size={32} />
                  <p className="text-sm">
                    {searchQuery || activeFilters
                      ? t("graph.noMatch")
                      : t("graph.noNotes")}
                  </p>
                </div>
              </div>
            )}
          {showGraph && (
            <ForceGraph2D
              ref={fgRef as never}
              graphData={filteredData}
              width={dimensions.width}
              height={dimensions.height}
              nodeCanvasObject={nodeCanvasObject}
              onNodeClick={handleNodeClick}
              linkColor={() => "rgba(60, 74, 66, 0.5)"}
              linkWidth={1.5}
              linkDirectionalParticles={1}
              linkDirectionalParticleWidth={2}
              nodePointerAreaPaint={(node: { x?: number; y?: number; id?: string }, color, ctx) => {
                // Generous hit area — minimum 12px so isolated/low-degree
                // nodes stay clickable even at default zoom.
                const deg = (node.id && degreeMap[node.id]) || 0;
                const r = Math.max(12, nodeRadius(deg, false) + 6);
                ctx.beginPath();
                ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
              }}
              d3VelocityDecay={0.4}
              warmupTicks={60}
              cooldownTicks={120}
              enableNodeDrag={true}
              enableZoomInteraction={true}
            />
          )}

          {/* Legend */}
          <div className="absolute bottom-6 left-6 flex flex-col gap-3 bg-surface-container-low/50 backdrop-blur p-4 rounded-xl border border-white/5">
            {/* Color mode toggle */}
            {communities.length > 0 && (
              <div className="flex gap-1 mb-1">
                <button
                  onClick={() => setColorMode("group")}
                  className={`min-h-10 px-2 py-0.5 rounded text-[9px] font-mono uppercase tracking-widest transition-all ${
                    colorMode === "group"
                      ? "bg-accent-light/20 text-accent-light"
                      : "text-gray-500 hover:text-gray-400"
                  }`}
                >
                  {t("graph.colorType")}
                </button>
                <button
                  onClick={() => setColorMode("community")}
                  className={`min-h-10 px-2 py-0.5 rounded text-[9px] font-mono uppercase tracking-widest transition-all ${
                    colorMode === "community"
                      ? "bg-accent-light/20 text-accent-light"
                      : "text-gray-500 hover:text-gray-400"
                  }`}
                >
                  {t("graph.colorCommunity")}
                </button>
              </div>
            )}

            {colorMode === "group"
              ? groupsInfo.map(({ group, count, label, color }) => {
                  const active = activeFilters === null || activeFilters.has(group);
                  return (
                    <button
                      key={group}
                      onClick={() => toggleFilter(group)}
                      className={`flex min-h-10 items-center gap-3 text-left transition-opacity ${
                        active ? "opacity-100" : "opacity-40 hover:opacity-70"
                      }`}
                    >
                      <div
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: color }}
                      />
                      <span className="font-mono text-[9px] uppercase tracking-widest text-gray-400">
                        {label}
                        <span className="text-gray-600 ml-1.5">{count}</span>
                      </span>
                    </button>
                  );
                })
              : communities.map((c) => (
                  <div key={c.id} className="flex items-center gap-3">
                    <div
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: c.color }}
                    />
                    <span className="font-mono text-[9px] tracking-widest text-gray-400 truncate max-w-[140px]">
                      {c.label}
                      <span className="text-gray-600 ml-1">({c.size})</span>
                    </span>
                  </div>
                ))}
          </div>
        </div>
      </div>

      {/* Right sidebar: node inspector */}
      {selectedNode && (
        <aside className="w-80 shrink-0 border-l border-accent-light/10 bg-surface flex flex-col overflow-hidden">
          {/* Sidebar header */}
          <div className="p-6 border-b border-outline-variant/10">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-accent-light/20 flex items-center justify-center">
                <Icon name="hub" className="text-accent-light" filled />
              </div>
              <div>
                <h2 className="font-headline font-bold text-accent-light leading-none">{t("graph.nodeInspector")}</h2>
                <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">v2.4.0</span>
              </div>
            </div>
            <div className="space-y-1">
              <h1 className="text-xl font-headline font-bold tracking-tight text-on-surface">
                {selectedNode.name}
              </h1>
              <div className="flex gap-2 flex-wrap">
                <span className="font-mono text-[10px] bg-accent-light/10 text-accent-light px-2 py-0.5 rounded">
                  {selectedNode.id.split("/").pop()}
                </span>
                <span className="font-mono text-[10px] bg-secondary/10 text-secondary px-2 py-0.5 rounded uppercase">
                  {selectedNode.group}
                </span>
                {nodeCommunityMap[selectedNode.id] && (
                  <span
                    className="font-mono text-[10px] px-2 py-0.5 rounded"
                    style={{
                      backgroundColor: nodeCommunityMap[selectedNode.id].color + "20",
                      color: nodeCommunityMap[selectedNode.id].color,
                    }}
                  >
                    {nodeCommunityMap[selectedNode.id].label}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-thin">
            {noteLoading && (
              <p className="text-xs text-gray-500">{t("common.loading")}</p>
            )}
            {!noteLoading && !noteContent && (
              <p className="text-xs text-gray-500">{t("graph.loadFailed")}</p>
            )}
            {!noteLoading && noteContent && parsed && (
              <>
                {/* Frontmatter */}
                {parsed.meta.length > 0 && (
                  <section>
                    <h3 className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mb-3">{t("graph.systemMetadata")}</h3>
                    <div className="grid grid-cols-2 gap-3">
                      {parsed.meta.map(({ key, value }, i) => (
                        <div key={i} className="bg-surface-container-low p-3 rounded">
                          <span className="block font-mono text-[9px] text-gray-500 uppercase">{key}</span>
                          <span className="font-mono text-xs text-accent-light">{value}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Body */}
                <section>
                  <h3 className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mb-3">{t("graph.previewContent")}</h3>
                  <div className="prose prose-sm prose-invert max-w-none prose-p:text-xs prose-headings:text-sm text-on-surface-variant">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkObsidian, remarkWikiLink]}
                      rehypePlugins={[
                        rehypeRaw,
                        [rehypeSanitize, sanitizeSchema],
                      ]}
                    >
                      {parsed.body}
                    </ReactMarkdown>
                  </div>
                </section>

                {/* Backlinks */}
                {backlinks.length > 0 && (
                  <section>
                    <h3 className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mb-3">
                      {t("graph.relatedNodes")}
                    </h3>
                    <div className="space-y-2">
                      {backlinks.map((bl) => (
                        <button
                          key={bl.path}
                          onClick={() => handleNodeClick({ id: bl.path })}
                          className="flex min-h-10 items-center gap-3 p-2 rounded hover:bg-white/5 transition-all cursor-pointer group w-full text-left"
                        >
                          <div className="w-2 h-2 rounded-full bg-accent-light" />
                          <span className="text-xs font-medium text-gray-300 group-hover:text-accent-light transition-colors flex-1 truncate">
                            {bl.title}
                          </span>
                          <Icon name="arrow_forward_ios" size={14} className="text-gray-600" />
                        </button>
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </div>

          {/* Sidebar footer */}
          <div className="p-6 border-t border-accent-light/10">
            <button
              onClick={() => {
                setSelectedNode(null);
                setNoteContent(null);
              }}
              className="w-full py-3 bg-gradient-to-r from-accent-light to-accent text-gray-950 font-headline font-bold text-xs uppercase tracking-widest rounded-lg hover:shadow-[0_0_20px_rgba(78,222,163,0.3)] transition-all active:scale-[0.98]"
            >
              {t("graph.closeInspector")}
            </button>
          </div>
        </aside>
      )}
    </div>
  );
}
