import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { GitBranch } from "lucide-react";
import { api } from "../../api/client";
import type { VaultGraph } from "../../api/types";

const GROUP_COLORS: Record<string, string> = {
  garden: "#10b981",
  seeds: "#3b82f6",
  actions: "#f59e0b",
  root: "#a78bfa",
};

export function MiniGraph() {
  const [graphData, setGraphData] = useState<VaultGraph | null>(null);
  const [loading, setLoading] = useState(true);
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

  const forceData = useMemo(() => {
    if (!graphData) return null;
    return {
      nodes: graphData.nodes.map((n) => ({ ...n })),
      links: graphData.links.map((l) => ({ ...l })),
    };
  }, [graphData]);

  const showGraph =
    !loading && forceData && forceData.nodes.length > 0 && dimensions;

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-gray-800/50">
        <GitBranch className="w-3 h-3 text-accent" />
        <span className="text-xs font-medium text-gray-400">
          Knowledge Graph
        </span>
        <a
          href="#/graph"
          className="ml-auto text-[10px] text-accent hover:text-accent-light transition-colors"
        >
          Expand
        </a>
      </div>
      <div ref={containerRef} className="h-40 relative bg-gray-950">
        {loading && (
          <div className="flex items-center justify-center h-full text-gray-600 text-xs">
            Loading...
          </div>
        )}
        {!loading && (!forceData || forceData.nodes.length === 0) && (
          <div className="flex items-center justify-center h-full text-gray-600 text-xs">
            No graph data
          </div>
        )}
        {showGraph && (
          <ForceGraph2D
            graphData={forceData}
            width={dimensions.width}
            height={dimensions.height}
            nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D) => {
              const color = GROUP_COLORS[node.group] || "#a78bfa";
              ctx.beginPath();
              ctx.arc(node.x, node.y, 2.5, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            nodePointerAreaPaint={(node: any, color, ctx) => {
              ctx.beginPath();
              ctx.arc(node.x, node.y, 4, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkColor={() => "rgba(42, 45, 66, 0.4)"}
            linkWidth={0.8}
            d3VelocityDecay={0.4}
            cooldownTicks={100}
            enableNodeDrag={false}
            enableZoomInteraction={false}
            enablePanInteraction={false}
          />
        )}
      </div>
    </div>
  );
}
