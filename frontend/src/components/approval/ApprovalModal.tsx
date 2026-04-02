import { ShieldAlert } from "lucide-react";
import type { ApprovalRequest } from "../../api/types";

interface ApprovalModalProps {
  request: ApprovalRequest;
  onRespond: (approved: boolean) => void;
}

export function ApprovalModal({ request, onRespond }: ApprovalModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-800 rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex items-center justify-center w-10 h-10 rounded-full bg-amber-900/40">
            <ShieldAlert className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-100">Approval Required</h3>
            <p className="text-sm text-gray-500">{request.skill_name}</p>
          </div>
        </div>

        <p className="text-sm text-gray-300 mb-2">{request.description}</p>

        {request.action_summary && (
          <div className="bg-gray-850 rounded-lg p-3 mb-4 text-xs text-gray-400 font-mono whitespace-pre-wrap">
            {request.action_summary}
          </div>
        )}

        <div className="flex gap-3 justify-end">
          <button
            onClick={() => onRespond(false)}
            className="px-4 py-2 text-sm rounded-lg border border-gray-700 text-gray-300 hover:bg-gray-800 transition-colors"
          >
            Deny
          </button>
          <button
            onClick={() => onRespond(true)}
            className="px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark transition-colors"
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
