import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkObsidian from "@thecae/remark-obsidian";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkWikiLink from "../../lib/remarkWikiLink";
import { api } from "../../api/client";
import type { VaultGraph, VaultGraphNode, VaultBacklink } from "../../api/types";
import { Icon } from "../common/Icon";

const NODE_COLORS: Record<string, string> = {
  garden: "#4edea3",
  seeds: "#adc6ff",
  actions: "#ffb95f",
  root: "#a78bfa",
};

const NODE_LABELS: Record<string, string> = {
  garden: "Ideas",
  seeds: "Seeds",
  actions: "Actions",
  root: "Other",
};

const NODE_ICONS: Record<string, string> = {
  garden: "lightbulb",
  seeds: "bolt",
  actions: "description",
  root: "folder_open",
};

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
  const [graphData, setGraphData] = useState<VaultGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilters, setActiveFilters] = useState<Set<string>>(
    new Set(["garden", "seeds", "actions", "root"]),
  );
  const [selectedNode, setSelectedNode] = useState<VaultGraphNode | null>(null);
  const [noteContent, setNoteContent] = useState<string | null>(null);
  const [noteLoading, setNoteLoading] = useState(false);
  const [backlinks, setBacklinks] = useState<VaultBacklink[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);
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

  const toggleFilter = useCallback((group: string) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(group)) {
        next.delete(group);
      } else {
        next.add(group);
      }
      return next;
    });
  }, []);

  const filteredData = useMemo(() => {
    if (!graphData) return null;
    const query = searchQuery.toLowerCase();
    const nodes = graphData.nodes.filter((n) => {
      if (!activeFilters.has(n.group)) return false;
      if (query && !n.name.toLowerCase().includes(query)) return false;
      return true;
    });
    const nodeIds = new Set(nodes.map((n) => n.id));
    const links = graphData.links.filter(
      (l) => nodeIds.has(l.source) && nodeIds.has(l.target),
    );
    return {
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    };
  }, [graphData, activeFilters, searchQuery]);

  const handleNodeClick = useCallback(async (node: { id?: string }) => {
    if (!node.id) return;
    const id = node.id as string;
    setSelectedNode({ id, name: (node as any).name || id, group: (node as any).group || "root" });
    setNoteLoading(true);
    setNoteContent(null);
    try {
      const res = await api.vaultFile(id);
      setNoteContent(res.content);
    } catch {
      setNoteContent(null);
    } finally {
      setNoteLoading(false);
    }
    try {
      const bl = await api.vaultBacklinks(id);
      setBacklinks(bl);
    } catch {
      setBacklinks([]);
    }
  }, []);

  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const label = node.name || "";
      const fontSize = Math.max(12 / globalScale, 3);
      const nodeColor = NODE_COLORS[node.group] || "#a78bfa";
      const isSelected = selectedNode?.id === node.id;
      const radius = isSelected ? 7 : 4;

      // Glow for selected node
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 10, 0, 2 * Math.PI);
        const gradient = ctx.createRadialGradient(
          node.x, node.y, radius,
          node.x, node.y, radius + 10,
        );
        gradient.addColorStop(0, nodeColor + "40");
        gradient.addColorStop(1, nodeColor + "00");
        ctx.fillStyle = gradient;
        ctx.fill();

        // Dashed orbit ring
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 6, 0, 2 * Math.PI);
        ctx.strokeStyle = nodeColor + "60";
        ctx.lineWidth = 1 / globalScale;
        ctx.setLineDash([4 / globalScale, 2 / globalScale]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Subtle glow for garden nodes
      if (node.group === "garden" && !isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(78, 222, 163, 0.12)";
        ctx.fill();
      }

      // Node circle
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = nodeColor;
      ctx.fill();

      // Selection ring
      if (isSelected) {
        ctx.strokeStyle = "#f2f3f7";
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      // Label
      ctx.font = `${fontSize}px "Plus Jakarta Sans", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = isSelected ? "#f2f3f7" : "#86948a";
      ctx.fillText(label, node.x, node.y + radius + 2);
    },
    [selectedNode],
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

  const groups = useMemo(() => {
    if (!graphData) return {};
    const counts: Record<string, number> = {};
    for (const n of graphData.nodes) {
      counts[n.group] = (counts[n.group] || 0) + 1;
    }
    return counts;
  }, [graphData]);

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
              placeholder="Explore network..."
              className="w-full pl-10 pr-8 py-1.5 rounded-lg border-b-2 border-transparent bg-surface-container-low text-sm text-on-surface outline-none focus:border-accent-light placeholder:text-gray-500 font-sans"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              >
                <Icon name="close" size={16} />
              </button>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            {Object.entries(NODE_LABELS).map(([group, label]) => {
              const icon = NODE_ICONS[group] || "folder_open";
              const color = NODE_COLORS[group] || "#a78bfa";
              const active = activeFilters.has(group);
              const count = groups[group] || 0;
              return (
                <button
                  key={group}
                  onClick={() => toggleFilter(group)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                    active
                      ? "bg-surface-container-high text-on-surface border border-white/5"
                      : "text-gray-500 border border-transparent hover:text-gray-400"
                  }`}
                >
                  <span
                    className="material-symbols-outlined"
                    style={{ fontSize: "14px", color: active ? color : undefined, opacity: active ? 1 : 0.5 }}
                  >
                    {icon}
                  </span>
                  {label}
                  {count > 0 && (
                    <span className="text-[10px] opacity-60">{count}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Graph canvas */}
        <div ref={containerRef} className="flex-1 min-h-0 relative bg-surface-dim">
          {loading && (
            <div className="flex items-center justify-center h-full text-gray-500">
              Loading graph...
            </div>
          )}
          {!loading &&
            (!filteredData || filteredData.nodes.length === 0) && (
              <div className="flex items-center justify-center h-full text-gray-500">
                <div className="text-center">
                  <Icon name="folder_open" className="mx-auto mb-2 opacity-50" size={32} />
                  <p className="text-sm">
                    {searchQuery || activeFilters.size < 4
                      ? "No nodes match your filters"
                      : "No notes to graph"}
                  </p>
                </div>
              </div>
            )}
          {showGraph && (
            <ForceGraph2D
              graphData={filteredData}
              width={dimensions.width}
              height={dimensions.height}
              nodeCanvasObject={nodeCanvasObject}
              onNodeClick={handleNodeClick}
              linkColor={() => "rgba(60, 74, 66, 0.5)"}
              linkWidth={1.5}
              linkDirectionalParticles={1}
              linkDirectionalParticleWidth={2}
              nodePointerAreaPaint={(node: any, color, ctx) => {
                ctx.beginPath();
                ctx.arc(node.x, node.y, 8, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
              }}
              d3VelocityDecay={0.3}
              cooldownTicks={200}
              enableNodeDrag={true}
              enableZoomInteraction={true}
            />
          )}

          {/* Legend */}
          <div className="absolute bottom-6 left-6 flex flex-col gap-3 bg-surface-container-low/50 backdrop-blur p-4 rounded-xl border border-white/5">
            {Object.entries(NODE_LABELS).map(([group, label]) => (
              <div key={group} className="flex items-center gap-3">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: NODE_COLORS[group] }}
                />
                <span className="font-mono text-[9px] uppercase tracking-widest text-gray-400">{label}</span>
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
                <h2 className="font-headline font-bold text-accent-light leading-none">Node Inspector</h2>
                <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">v2.4.0</span>
              </div>
            </div>
            <div className="space-y-1">
              <h1 className="text-xl font-headline font-bold tracking-tight text-on-surface">
                {selectedNode.name}
              </h1>
              <div className="flex gap-2">
                <span className="font-mono text-[10px] bg-accent-light/10 text-accent-light px-2 py-0.5 rounded">
                  {selectedNode.id.split("/").pop()}
                </span>
                <span className="font-mono text-[10px] bg-secondary/10 text-secondary px-2 py-0.5 rounded uppercase">
                  {selectedNode.group}
                </span>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-thin">
            {noteLoading && (
              <p className="text-xs text-gray-500">Loading...</p>
            )}
            {!noteLoading && !noteContent && (
              <p className="text-xs text-gray-500">Unable to load note content.</p>
            )}
            {!noteLoading && noteContent && parsed && (
              <>
                {/* Frontmatter */}
                {parsed.meta.length > 0 && (
                  <section>
                    <h3 className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mb-3">System Metadata</h3>
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
                  <h3 className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mb-3">Preview Content</h3>
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
                      Related Nodes
                    </h3>
                    <div className="space-y-2">
                      {backlinks.map((bl) => (
                        <button
                          key={bl.path}
                          onClick={() => handleNodeClick({ id: bl.path })}
                          className="flex items-center gap-3 p-2 rounded hover:bg-white/5 transition-all cursor-pointer group w-full text-left"
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
              Close Inspector
            </button>
          </div>
        </aside>
      )}
    </div>
  );
}
