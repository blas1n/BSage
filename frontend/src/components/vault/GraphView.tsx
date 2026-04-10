import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { api } from "../../api/client";
import type { VaultGraph } from "../../api/types";

interface GraphViewProps {
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
}

const GROUP_COLORS: Record<string, string> = {
  garden: "#10b981",   // emerald accent
  seeds: "#3b82f6",
  actions: "#f59e0b",
  root: "#a78bfa",
};

export function GraphView({ onSelectFile, selectedPath }: GraphViewProps) {
  const [graphData, setGraphData] = useState<VaultGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null);

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

  const handleNodeClick = useCallback(
    (node: { id?: string }) => {
      if (node.id) onSelectFile(node.id as string);
    },
    [onSelectFile],
  );

  // react-force-graph-2d mutates data objects in place -- deep-clone to avoid stale refs
  const forceData = useMemo(() => {
    if (!graphData) return null;
    return {
      nodes: graphData.nodes.map((n) => ({ ...n })),
      links: graphData.links.map((l) => ({ ...l })),
    };
  }, [graphData]);

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
      const nodeColor = GROUP_COLORS[group] || "#a78bfa";
      const isSelected = rawNode.id === selectedPath;
      const radius = isSelected ? 6 : 4;

      // Glow effect for emerald nodes
      if (group === "garden") {
        ctx.beginPath();
        ctx.arc(x, y, radius + 3, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(16, 185, 129, 0.15)";
        ctx.fill();
      }

      // Node circle
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = nodeColor;
      ctx.fill();

      // Selection ring
      if (isSelected) {
        ctx.strokeStyle = "#e4e6ee";
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      // Label
      ctx.font = `${fontSize}px "Plus Jakarta Sans", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "#a8adc6";
      ctx.fillText(label, x, y + radius + 2);
    },
    [selectedPath],
  );

  const showGraph =
    !loading && forceData && forceData.nodes.length > 0 && dimensions;

  return (
    <div ref={containerRef} className="w-full h-full absolute inset-0 bg-gray-950">
      {loading && (
        <div className="flex items-center justify-center h-full text-gray-600">
          Loading graph...
        </div>
      )}

      {!loading && (!forceData || forceData.nodes.length === 0) && (
        <div className="flex items-center justify-center h-full text-gray-600">
          <p className="text-sm">No notes to graph</p>
        </div>
      )}

      {showGraph && (
        <ForceGraph2D
          graphData={forceData}
          width={dimensions.width}
          height={dimensions.height}
          nodeCanvasObject={nodeCanvasObject}
          onNodeClick={handleNodeClick}
          linkColor={() => "rgba(42, 45, 66, 0.6)"}
          linkWidth={1.5}
          linkDirectionalParticles={1}
          linkDirectionalParticleWidth={2}
          nodePointerAreaPaint={(node: { x?: number; y?: number }, color, ctx) => {
            ctx.beginPath();
            ctx.arc(node.x ?? 0, node.y ?? 0, 8, 0, 2 * Math.PI);
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
  );
}
