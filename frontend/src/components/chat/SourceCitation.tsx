import { FileText } from "lucide-react";

interface SourceCitationProps {
  sources: string[];
  onNavigate?: (path: string) => void;
}

/** Extract wikilink targets from markdown text. */
export function extractWikilinks(text: string): string[] {
  const matches = text.matchAll(/\[\[([^\]]+)\]\]/g);
  const seen = new Set<string>();
  const result: string[] = [];
  for (const m of matches) {
    const target = m[1].split("|")[0].trim();
    if (!seen.has(target)) {
      seen.add(target);
      result.push(target);
    }
  }
  return result;
}

export function SourceCitation({ sources, onNavigate }: SourceCitationProps) {
  if (sources.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-gray-800/50">
      <span className="text-[10px] text-gray-500 leading-5">Sources:</span>
      {sources.map((source) => (
        <button
          key={source}
          onClick={() => onNavigate?.(source)}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-accent/15 text-accent border border-accent/20 hover:bg-accent/25 transition-colors"
        >
          <FileText className="w-2.5 h-2.5" />
          {source}
        </button>
      ))}
    </div>
  );
}
