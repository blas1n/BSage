import { FileText, Search, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { VaultSearchResult } from "../../api/types";

interface SearchPanelProps {
  onSelectFile: (path: string) => void;
}

export function SearchPanel({ onSelectFile }: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<VaultSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const data = await api.vaultSearch(q);
      setResults(data);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, []);

  useEffect(() => {
    clearTimeout(timerRef.current);
    if (!query.trim()) {
      setResults([]);
      return;
    }
    timerRef.current = setTimeout(() => doSearch(query), 300);
    return () => clearTimeout(timerRef.current);
  }, [query, doSearch]);

  const isActive = query.trim().length > 0;

  return (
    <div className="mb-2">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search vault..."
          style={{ paddingLeft: "1.2rem" }}
          className="w-full pr-8 py-1.5 text-xs bg-gray-900 border border-gray-800 rounded-md focus:outline-none focus:ring-1 focus:ring-accent text-gray-300 placeholder-gray-600"
        />
        {isActive && (
          <button
            onClick={() => setQuery("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-300"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {isActive && (
        <div className="mt-1 max-h-64 overflow-y-auto scrollbar-thin">
          {searching && (
            <p className="text-xs text-gray-600 py-2 text-center">Searching...</p>
          )}
          {!searching && results.length === 0 && (
            <p className="text-xs text-gray-600 py-2 text-center">No results</p>
          )}
          {!searching &&
            results.map((r) => (
              <button
                key={r.path}
                onClick={() => {
                  onSelectFile(r.path);
                  setQuery("");
                }}
                className="w-full text-left px-2 py-1.5 text-xs hover:bg-gray-800/50 rounded transition-colors"
              >
                <div className="flex items-center gap-1.5">
                  <FileText className="w-3 h-3 text-gray-600 shrink-0" />
                  <span className="font-medium text-gray-300 truncate">
                    {r.path}
                  </span>
                </div>
                {r.matches.length > 0 && (
                  <p className="mt-0.5 text-[10px] text-gray-600 truncate pl-4.5">
                    {r.matches[0].text}
                  </p>
                )}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

