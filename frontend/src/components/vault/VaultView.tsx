import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkObsidian from "@thecae/remark-obsidian";
import remarkWikiLink from "../../lib/remarkWikiLink";
import { api } from "../../api/client";
import type { VaultBacklink, VaultTreeEntry } from "../../api/types";
import { Icon } from "../common/Icon";
import { BacklinksPanel } from "./BacklinksPanel";
import { DirectoryTree } from "./DirectoryTree";
import { GraphView } from "./GraphView";
import { SearchPanel } from "./SearchPanel";
import { TagCloud } from "./TagCloud";

/** Split YAML frontmatter from the markdown body. */
function splitFrontmatter(text: string): { meta: Record<string, string>[]; body: string } {
  if (!text.startsWith("---\n")) return { meta: [], body: text };
  const endIdx = text.indexOf("\n---\n", 4);
  if (endIdx === -1) return { meta: [], body: text };

  const yamlBlock = text.slice(4, endIdx);
  const body = text.slice(endIdx + 5);

  const entries: Record<string, string>[] = [];
  for (const line of yamlBlock.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const colonIdx = trimmed.indexOf(":");
    if (colonIdx === -1) continue;
    const key = trimmed.slice(0, colonIdx).trim();
    let val = trimmed.slice(colonIdx + 1).trim();
    if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
      val = val.slice(1, -1);
    }
    entries.push({ key, value: val });
  }
  return { meta: entries, body };
}

/** Build a lookup: lowercase filename stem -> relative path. */
function buildStemLookup(tree: VaultTreeEntry[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const entry of tree) {
    for (const file of entry.files) {
      if (!file.endsWith(".md")) continue;
      const stem = file.replace(/\.md$/, "").toLowerCase();
      const fullPath = entry.path ? `${entry.path}/${file}` : file;
      if (!map.has(stem)) {
        map.set(stem, fullPath);
      } else if (import.meta.env.DEV) {
        console.warn(`VaultView: stem collision for "${stem}" — "${fullPath}" ignored, using "${map.get(stem)}"`);
      }
    }
  }
  return map;
}

type ViewMode = "notes" | "graph";

function ViewModeTabs({
  current,
  onChange,
}: {
  current: ViewMode;
  onChange: (mode: ViewMode) => void;
}) {
  return (
    <div className="flex items-center gap-6">
      <button
        onClick={() => onChange("notes")}
        className={`text-sm font-semibold tracking-tight px-2 py-1 rounded transition-colors ${
          current === "notes" ? "text-accent-light" : "text-on-surface/60 hover:bg-surface-container-low"
        }`}
      >
        Vault Explorer
      </button>
      <button
        onClick={() => onChange("graph")}
        className={`text-sm font-semibold tracking-tight px-2 py-1 rounded transition-colors ${
          current === "graph" ? "text-accent-light" : "text-on-surface/60 hover:bg-surface-container-low"
        }`}
      >
        Graph View
      </button>
    </div>
  );
}

export function VaultView() {
  const [tree, setTree] = useState<VaultTreeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [rawMode, setRawMode] = useState(false);
  const [backlinks, setBacklinks] = useState<VaultBacklink[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>("notes");
  const [filterPaths, setFilterPaths] = useState<Set<string> | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);

  useEffect(() => {
    api
      .vaultTree()
      .then(setTree)
      .finally(() => setLoading(false));
  }, []);

  const stemLookup = useMemo(() => buildStemLookup(tree), [tree]);

  const handleSelectFile = useCallback(async (path: string) => {
    setSelectedPath(path);
    setFileLoading(true);
    setRawMode(false);
    setViewMode("notes");
    try {
      const res = await api.vaultFile(path);
      setFileContent(res.content);
    } catch {
      setFileContent("Failed to load file.");
    } finally {
      setFileLoading(false);
    }
    try {
      const bl = await api.vaultBacklinks(path);
      setBacklinks(bl);
    } catch {
      setBacklinks([]);
    }
  }, []);

  const resolveWikiLink = useCallback(
    (target: string): string | null => {
      const lower = target.toLowerCase();
      if (stemLookup.has(lower)) return stemLookup.get(lower)!;
      const withMd = lower.endsWith(".md") ? lower : lower + ".md";
      for (const entry of tree) {
        for (const file of entry.files) {
          const fullPath = entry.path ? `${entry.path}/${file}` : file;
          if (fullPath.toLowerCase() === withMd) return fullPath;
        }
      }
      return null;
    },
    [stemLookup, tree],
  );

  const handleTagSelect = useCallback(
    (tag: string | null) => {
      setActiveTag(tag);
      if (!tag) {
        setFilterPaths(null);
        return;
      }
      api
        .vaultTags()
        .then((data) => {
          const paths = data.tags[tag];
          setFilterPaths(paths ? new Set(paths) : new Set());
        })
        .catch(() => setFilterPaths(null));
    },
    [],
  );

  const parsed = useMemo(() => {
    if (!fileContent) return null;
    return splitFrontmatter(fileContent);
  }, [fileContent]);

  const markdownComponents = useMemo(
    () => ({
      a: ({
        href,
        children,
        ...props
      }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
        if (href?.startsWith("wikilink://")) {
          const target = decodeURIComponent(href.slice("wikilink://".length));
          const resolved = resolveWikiLink(target);
          return (
            <a
              {...props}
              className={`wikilink ${!resolved ? "unresolved" : ""}`}
              onClick={(e) => {
                e.preventDefault();
                if (resolved) handleSelectFile(resolved);
              }}
              href="#"
              title={resolved || `${target} (not found)`}
            >
              {children}
            </a>
          );
        }
        const isSafeUrl = href && /^https?:\/\//i.test(href);
        return (
          <a
            href={isSafeUrl ? href : "#"}
            {...props}
            target="_blank"
            rel="noopener noreferrer"
            onClick={isSafeUrl ? undefined : (e) => e.preventDefault()}
          >
            {children}
          </a>
        );
      },
    }),
    [resolveWikiLink, handleSelectFile],
  );

  const handleGraphSelect = useCallback(
    (path: string) => {
      setViewMode("notes");
      handleSelectFile(path);
    },
    [handleSelectFile],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">Loading...</div>
    );
  }

  // Extract breadcrumb parts from selectedPath
  const breadcrumb = selectedPath ? selectedPath.replace(/\.md$/, "").split("/") : [];

  return (
    <div className="h-full flex flex-col">
      {/* Top navigation */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-white/5 bg-surface shrink-0">
        <ViewModeTabs current={viewMode} onChange={setViewMode} />
        <div className="flex items-center gap-3">
          {selectedPath && (
            <>
              <button className="text-on-surface/60 hover:bg-surface-container-low p-2 rounded transition-colors">
                <Icon name="edit" size={18} />
              </button>
              <button className="text-accent-light hover:bg-surface-container-low p-2 rounded transition-colors">
                <Icon name="sync" size={18} />
              </button>
            </>
          )}
        </div>
      </header>

      {viewMode === "graph" ? (
        <div className="flex-1 min-h-0 relative">
          <GraphView onSelectFile={handleGraphSelect} selectedPath={selectedPath} />
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex">
          {/* Left panel: file tree */}
          <div data-testid="vault-file-tree" className="w-72 shrink-0 bg-surface-container-low border-r border-outline-variant/5 flex flex-col">
            {/* Search */}
            <div className="p-4">
              <div className="relative group">
                <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400/50 group-focus-within:text-accent-light transition-colors" size={18} />
                <input
                  className="w-full bg-surface-dim border-none border-b-2 border-transparent focus:ring-0 focus:border-accent-light text-sm pl-10 pr-4 py-2 text-on-surface placeholder:text-gray-400/40 transition-all font-sans"
                  placeholder="Search vault..."
                  type="text"
                />
              </div>
              <SearchPanel onSelectFile={handleSelectFile} />
            </div>

            {/* Sidebar categories */}
            <div className="px-2 space-y-1 mb-4">
              <button className="w-full flex items-center gap-3 bg-accent-light/10 text-accent-light border-r-2 border-accent-light px-4 py-3 font-mono text-xs uppercase tracking-widest transition-all">
                <Icon name="psychology" size={18} />
                Seeds
              </button>
              <button className="w-full flex items-center gap-3 text-on-surface/40 px-4 py-3 font-mono text-xs uppercase tracking-widest hover:text-accent-light hover:bg-surface-container-low transition-all">
                <Icon name="local_florist" size={18} />
                Garden
              </button>
              <button className="w-full flex items-center gap-3 text-on-surface/40 px-4 py-3 font-mono text-xs uppercase tracking-widest hover:text-accent-light hover:bg-surface-container-low transition-all">
                <Icon name="bolt" size={18} />
                Actions
              </button>
            </div>

            {/* Tag cloud */}
            <div className="px-3">
              <TagCloud activeTag={activeTag} onSelectTag={handleTagSelect} />
            </div>

            {/* Directory tree */}
            <div className="flex-1 overflow-y-auto font-mono text-[11px] py-2 px-3 scrollbar-thin">
              {tree.length === 0 || (tree.length === 1 && tree[0].dirs.length === 0 && tree[0].files.length === 0) ? (
                <div className="text-center py-8 text-gray-500">
                  <Icon name="folder_open" className="mx-auto mb-2 opacity-50" size={24} />
                  <p className="text-xs font-sans">Vault is empty</p>
                </div>
              ) : (
                <DirectoryTree
                  tree={tree}
                  selectedPath={selectedPath}
                  onSelectFile={handleSelectFile}
                  filterPaths={filterPaths}
                />
              )}
            </div>

            {/* New Note button */}
            <div className="p-4">
              <button className="w-full py-2 bg-accent text-gray-950 font-bold text-xs uppercase tracking-widest rounded hover:bg-accent-light transition-colors">
                New Note
              </button>
            </div>
          </div>

          {/* Right panel: note detail */}
          <div data-testid="vault-file-content" className="flex-1 flex flex-col min-w-0 bg-surface-dim">
            {/* Breadcrumb bar */}
            {selectedPath && (
              <div className="h-12 border-b border-outline-variant/10 flex items-center justify-between px-6 bg-surface shrink-0">
                <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-gray-400/40">
                  <span>Vault</span>
                  {breadcrumb.map((part, i) => (
                    <span key={i} className="flex items-center gap-2">
                      <Icon name="chevron_right" size={12} />
                      <span className={i === breadcrumb.length - 1 ? "text-on-surface/80" : "text-accent-light/80"}>
                        {part}
                      </span>
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-4">
                  <button
                    onClick={() => setRawMode((r) => !r)}
                    className="flex items-center gap-2 text-xs text-on-surface/60 hover:text-accent-light transition-colors"
                  >
                    <Icon name={rawMode ? "visibility" : "code"} size={18} />
                    <span>{rawMode ? "Rendered" : "Raw"}</span>
                  </button>
                  <div className="h-4 w-px bg-outline-variant/30" />
                  <div className="flex items-center gap-1.5">
                    <div className="w-1.5 h-1.5 rounded-full bg-accent-light shadow-[0_0_8px_rgba(78,222,163,0.5)]" />
                    <span className="text-[10px] font-mono text-accent-light/80 uppercase">Synced</span>
                  </div>
                </div>
              </div>
            )}

            {/* Content area */}
            <div className="flex-1 overflow-y-auto scrollbar-thin">
              {!selectedPath && (
                <div className="flex items-center justify-center h-full text-gray-500">
                  <div className="text-center">
                    <Icon name="folder_open" className="mx-auto mb-2 opacity-50" size={32} />
                    <p className="text-sm font-sans">Select a file to view its contents</p>
                  </div>
                </div>
              )}
              {selectedPath && fileLoading && (
                <div className="px-12 py-10">
                  <p className="text-sm text-gray-500">Loading...</p>
                </div>
              )}
              {selectedPath && !fileLoading && fileContent !== null && (
                <div className="px-12 py-10 max-w-4xl mx-auto w-full">
                  {rawMode ? (
                    <pre data-testid="vault-raw-content" className="text-xs text-gray-300 bg-surface-container-low rounded-lg p-6 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed border border-outline-variant/10">
                      {fileContent}
                    </pre>
                  ) : (
                    <div>
                      {/* Frontmatter metadata */}
                      {parsed && parsed.meta.length > 0 && (
                        <div className="mb-8 rounded bg-surface-container-low/50 border border-outline-variant/10 overflow-hidden">
                          <div className="px-4 py-2 flex items-center justify-between cursor-pointer hover:bg-surface-container-high transition-colors">
                            <div className="flex items-center gap-2 text-[10px] font-mono text-gray-400 uppercase tracking-widest">
                              <Icon name="expand_more" size={14} />
                              Metadata (YAML)
                            </div>
                            <span className="text-[10px] font-mono text-gray-400/40">{parsed.meta.length} fields</span>
                          </div>
                        </div>
                      )}

                      {/* Title */}
                      <h1 className="text-4xl font-extrabold text-on-surface mb-2 tracking-tight font-headline">
                        {selectedPath.split("/").pop()?.replace(/\.md$/, "") || selectedPath}
                      </h1>

                      {/* Tags as badges */}
                      {parsed && parsed.meta.some(m => m.key === "tags") && (
                        <div className="flex flex-wrap gap-2 mb-10">
                          {parsed.meta
                            .filter(m => m.key === "tags")
                            .map(m => m.value.split(",").map(t => t.trim()))
                            .flat()
                            .map((tag) => (
                              <span key={tag} className="bg-accent-light/10 text-accent-light border border-accent-light/20 px-2 py-0.5 rounded-sm text-[10px] font-mono uppercase tracking-wider">
                                #{tag}
                              </span>
                            ))}
                        </div>
                      )}

                      {/* Markdown body */}
                      <article className="prose prose-invert max-w-none text-on-surface/80 font-sans leading-relaxed">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, remarkObsidian, remarkWikiLink]}
                          rehypePlugins={[rehypeRaw, [rehypeSanitize, { ...defaultSchema, attributes: { ...defaultSchema.attributes, "*": [...(defaultSchema.attributes?.["*"] || []), "className"] } }]]}
                          components={markdownComponents}
                        >
                          {parsed?.body ?? fileContent}
                        </ReactMarkdown>
                      </article>

                      {/* Backlinks */}
                      <BacklinksPanel backlinks={backlinks} onNavigate={handleSelectFile} />
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer metadata bar */}
            {selectedPath && !fileLoading && parsed && (
              <footer className="h-10 bg-surface-dim border-t border-outline-variant/10 flex items-center px-6 gap-8 overflow-x-auto whitespace-nowrap shrink-0">
                {parsed.meta.slice(0, 4).map(({ key, value }, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] font-mono">
                    <span className="text-gray-400 uppercase tracking-tighter">{key}:</span>
                    <span className="text-accent-light font-bold">{value}</span>
                  </div>
                ))}
                {backlinks.length > 0 && (
                  <div className="ml-auto flex items-center gap-2 text-[10px] font-mono">
                    <Icon name="hub" className="text-accent-light" size={14} />
                    <span className="text-accent-light font-bold">{backlinks.length} Nodes</span>
                    <span className="text-gray-400 uppercase tracking-tighter ml-1">Related</span>
                  </div>
                )}
              </footer>
            )}
          </div>
        </div>
      )}

      {/* FAB */}
      <button className="fixed bottom-14 right-8 w-14 h-14 bg-accent-light text-gray-950 rounded-full shadow-[0_8px_24px_rgba(0,0,0,0.5)] flex items-center justify-center hover:scale-110 active:scale-95 transition-transform z-50 group">
        <Icon name="add" size={24} filled weight={600} />
        <div className="absolute right-full mr-4 bg-surface-container-highest text-on-surface text-[10px] font-bold uppercase tracking-widest px-3 py-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none border border-outline-variant/20">
          Create Seed
        </div>
      </button>
    </div>
  );
}
