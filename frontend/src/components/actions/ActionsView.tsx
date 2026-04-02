import { ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";

export function ActionsView() {
  const [actions, setActions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.actions().then((a) => {
      setActions(a.reverse());
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600">Loading...</div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 scrollbar-thin">
      <h2 className="text-lg font-semibold mb-4 text-gray-100">Action Log</h2>
      {actions.length === 0 ? (
        <div className="text-center py-12 text-gray-600">
          <ScrollText className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No actions recorded yet</p>
        </div>
      ) : (
        <div className="space-y-1">
          {actions.map((name) => (
            <div
              key={name}
              className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-800/50 text-sm"
            >
              <ScrollText className="w-4 h-4 text-gray-600 shrink-0" />
              <span className="text-gray-300 font-mono text-xs truncate">
                {name}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
