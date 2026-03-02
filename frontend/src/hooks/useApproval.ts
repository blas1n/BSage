import { useCallback, useEffect, useState } from "react";
import type { ApprovalRequest } from "../api/types";
import { wsManager } from "../api/websocket";

export function useApproval() {
  const [queue, setQueue] = useState<ApprovalRequest[]>([]);

  useEffect(() => {
    return wsManager.subscribe((msg) => {
      if (msg.type === "approval_request") {
        setQueue((prev) => [...prev, msg as ApprovalRequest]);
      }
    });
  }, []);

  const current = queue[0] ?? null;

  const respond = useCallback(
    (approved: boolean) => {
      if (!current) return;
      wsManager.send({
        type: "approval_response",
        request_id: current.request_id,
        approved,
      });
      setQueue((prev) => prev.slice(1));
    },
    [current],
  );

  return { current, respond, pendingCount: queue.length };
}
