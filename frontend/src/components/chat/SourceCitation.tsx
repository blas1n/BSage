import { Icon } from "../common/Icon";

interface SourceCitationProps {
  sources: string[];
  onNavigate?: (path: string) => void;
}

export function SourceCitation({ sources, onNavigate }: SourceCitationProps) {
  if (sources.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-4 mt-6 pt-4 border-t border-outline-variant/10">
      {sources.map((source) => (
        <button
          key={source}
          onClick={() => onNavigate?.(source)}
          className="flex items-center gap-1.5 group"
        >
          <Icon name="description" className="text-gray-400 text-xs" size={14} />
          <span className="font-mono text-[11px] text-gray-400 group-hover:text-accent-light transition-colors">
            {source}
          </span>
        </button>
      ))}
    </div>
  );
}
