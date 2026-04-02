import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { Icon } from "../common/Icon";
import { api } from "../../api/client";
import type { VaultGraph } from "../../api/types";

const GROUP_COLORS: Record<string, string> = {
  garden: "#4edea3",
  seeds: "#adc6ff",
  actions: "#ffb95f",
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
    <div className="rounded-xl border border-white/5 bg-surface overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-white/5">
        <Icon name="hub" className="text-accent-light" size={16} />
        <span className="text-xs font-medium text-gray-400">
          Knowledge Graph
        </span>
        <a
          href="#/graph"
          className="ml-auto text-[10px] text-accent-light hover:text-accent-light/80 transition-colors font-mono uppercase tracking-wider"
        >
          Expand
        </a>
      </div>
      <div ref={containerRef} className="h-40 relative bg-surface-dim">
        {loading && (
          <div className="flex items-center justify-center h-full text-gray-500 text-xs">
            Loading...
          </div>
        )}
        {!loading && (!forceData || forceData.nodes.length === 0) && (
          <div className="flex items-center justify-center h-full text-gray-500 text-xs">
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
            linkColor={() => "rgba(60, 74, 66, 0.4)"}
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
