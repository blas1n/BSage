import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import {
  Search,
  X,
  FileText,
  Lightbulb,
  Zap,
  FolderOpen,
  ChevronRight,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkObsidian from "@thecae/remark-obsidian";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkWikiLink from "../../lib/remarkWikiLink";
import { api } from "../../api/client";
import type { VaultGraph, VaultGraphNode, VaultBacklink } from "../../api/types";

const NODE_COLORS: Record<string, string> = {
  garden: "#10b981",
  seeds: "#3b82f6",
  actions: "#f59e0b",
  root: "#a78bfa",
};

const NODE_LABELS: Record<string, string> = {
  garden: "Ideas & Insights",
  seeds: "Seeds",
  actions: "Actions",
  root: "Other",
};

const NODE_ICONS: Record<string, typeof Lightbulb> = {
  garden: Lightbulb,
  seeds: Zap,
  actions: FileText,
  root: FolderOpen,
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
        ctx.arc(node.x, node.y, radius + 8, 0, 2 * Math.PI);
        const gradient = ctx.createRadialGradient(
          node.x,
          node.y,
          radius,
          node.x,
          node.y,
          radius + 8,
        );
        gradient.addColorStop(0, nodeColor + "40");
        gradient.addColorStop(1, nodeColor + "00");
        ctx.fillStyle = gradient;
        ctx.fill();
      }

      // Subtle glow for garden nodes
      if (node.group === "garden" && !isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(16, 185, 129, 0.12)";
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
      ctx.fillStyle = isSelected ? "#f2f3f7" : "#8187a8";
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
    <div className="flex h-full">
      {/* Main graph area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar: search + filters */}
        <div className="shrink-0 px-4 py-3 border-b border-gray-800/50 flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search nodes..."
              className="w-full pl-9 pr-8 py-1.5 rounded-lg border border-gray-700 bg-gray-850 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            {Object.entries(NODE_LABELS).map(([group, label]) => {
              const Icon = NODE_ICONS[group] || FolderOpen;
              const color = NODE_COLORS[group] || "#a78bfa";
              const active = activeFilters.has(group);
              const count = groups[group] || 0;
              return (
                <button
                  key={group}
                  onClick={() => toggleFilter(group)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                    active
                      ? "bg-gray-800 text-gray-200 border border-gray-700"
                      : "text-gray-500 border border-transparent hover:text-gray-400"
                  }`}
                >
                  <Icon
                    className="w-3 h-3"
                    style={{ color: active ? color : undefined }}
                  />
                  {label}
                  {count > 0 && (
                    <span
                      className="text-[10px] opacity-60"
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Graph canvas */}
        <div ref={containerRef} className="flex-1 min-h-0 relative bg-gray-950">
          {loading && (
            <div className="flex items-center justify-center h-full text-gray-600">
              Loading graph...
            </div>
          )}
          {!loading &&
            (!filteredData || filteredData.nodes.length === 0) && (
              <div className="flex items-center justify-center h-full text-gray-600">
                <div className="text-center">
                  <FolderOpen className="w-8 h-8 mx-auto mb-2 opacity-50" />
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
              linkColor={() => "rgba(42, 45, 66, 0.6)"}
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
        </div>
      </div>

      {/* Right sidebar: note detail */}
      {selectedNode && (
        <div className="w-80 shrink-0 border-l border-gray-800 bg-gray-900 flex flex-col overflow-hidden">
          {/* Sidebar header */}
          <div className="px-4 py-3 border-b border-gray-800/50 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <div
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{
                  backgroundColor:
                    NODE_COLORS[selectedNode.group] || "#a78bfa",
                }}
              />
              <span className="text-sm font-medium text-gray-100 truncate">
                {selectedNode.name}
              </span>
            </div>
            <button
              onClick={() => {
                setSelectedNode(null);
                setNoteContent(null);
              }}
              className="text-gray-500 hover:text-gray-300 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* File path */}
          <div className="px-4 py-2 border-b border-gray-800/30 shrink-0">
            <p className="text-[11px] text-gray-500 font-mono truncate">
              {selectedNode.id}
            </p>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-4 py-3 scrollbar-thin">
            {noteLoading && (
              <p className="text-xs text-gray-600">Loading...</p>
            )}
            {!noteLoading && !noteContent && (
              <p className="text-xs text-gray-600">
                Unable to load note content.
              </p>
            )}
            {!noteLoading && noteContent && parsed && (
              <div>
                {/* Frontmatter */}
                {parsed.meta.length > 0 && (
                  <div className="mb-3 rounded-lg border border-gray-800 overflow-hidden">
                    <table className="w-full text-xs">
                      <tbody>
                        {parsed.meta.map(({ key, value }, i) => (
                          <tr
                            key={i}
                            className={
                              i % 2 === 0 ? "bg-gray-850/50" : "bg-gray-850"
                            }
                          >
                            <td className="px-2.5 py-1 font-medium text-gray-500 whitespace-nowrap">
                              {key}
                            </td>
                            <td className="px-2.5 py-1 text-gray-300 font-mono break-all">
                              {value}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Markdown body */}
                <div className="prose prose-sm prose-invert max-w-none prose-p:text-xs prose-headings:text-sm">
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

                {/* Backlinks */}
                {backlinks.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-gray-800">
                    <h4 className="text-xs font-medium text-gray-500 mb-2">
                      Backlinks ({backlinks.length})
                    </h4>
                    <div className="space-y-1">
                      {backlinks.map((bl) => (
                        <button
                          key={bl.path}
                          onClick={() =>
                            handleNodeClick({ id: bl.path })
                          }
                          className="flex items-center gap-1.5 w-full text-left px-2 py-1 rounded text-xs text-gray-400 hover:text-accent hover:bg-gray-850 transition-colors"
                        >
                          <ChevronRight className="w-3 h-3 shrink-0" />
                          <span className="truncate">{bl.title}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
