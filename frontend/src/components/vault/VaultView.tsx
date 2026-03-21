import { Code, Eye, FolderOpen, GitBranch, FileText } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkObsidian from "@thecae/remark-obsidian";
import remarkWikiLink from "../../lib/remarkWikiLink";
import { api } from "../../api/client";
import type { VaultBacklink, VaultTreeEntry } from "../../api/types";
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

/** Build a lookup: lowercase filename stem → relative path. */
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
  className,
}: {
  current: ViewMode;
  onChange: (mode: ViewMode) => void;
  className?: string;
}) {
  const base = "flex items-center gap-1.5 px-4 py-2 rounded-md text-xs font-medium transition-colors";
  const active = "bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-100 shadow-sm";
  const inactive = "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300";
  return (
    <div className={`flex items-center gap-0.5 rounded-lg p-1 ${className ?? ""}`}>
      <button onClick={() => onChange("notes")} className={`${base} ${current === "notes" ? active : inactive}`}>
        <FileText className="w-3.5 h-3.5" />
        Notes
      </button>
      <button onClick={() => onChange("graph")} className={`${base} ${current === "graph" ? active : inactive}`}>
        <GitBranch className="w-3.5 h-3.5" />
        Graph
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
    // Fetch backlinks
    try {
      const bl = await api.vaultBacklinks(path);
      setBacklinks(bl);
    } catch {
      setBacklinks([]);
    }
  }, []);

  /** Resolve a wikilink target to a vault path. */
  const resolveWikiLink = useCallback(
    (target: string): string | null => {
      const lower = target.toLowerCase();
      // Try exact stem match
      if (stemLookup.has(lower)) return stemLookup.get(lower)!;
      // Try with .md extension
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

  /** Custom link component for wikilinks */
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
      <div className="flex items-center justify-center h-full text-gray-400">Loading...</div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {viewMode === "graph" ? (
        /* Graph mode */
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="px-6 pt-3 pb-2 shrink-0 flex items-center justify-end">
            <ViewModeTabs
              current={viewMode}
              onChange={setViewMode}
              className="bg-gray-100 dark:bg-gray-800"
            />
          </div>
          <div className="flex-1 min-h-0 relative">
            <GraphView onSelectFile={handleGraphSelect} selectedPath={selectedPath} />
          </div>
        </div>
      ) : (
        /* Notes mode */
        <div className="flex-1 min-h-0 flex">
          {/* Left panel: title + search + tags + directory tree */}
          <div data-testid="vault-file-tree" className="w-56 shrink-0 border-r border-gray-200 dark:border-gray-700 overflow-y-auto p-3 scrollbar-thin">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-3">Vault</h2>
            <SearchPanel onSelectFile={handleSelectFile} />

            <TagCloud activeTag={activeTag} onSelectTag={handleTagSelect} />

            {tree.length === 0 || (tree.length === 1 && tree[0].dirs.length === 0 && tree[0].files.length === 0) ? (
              <div className="text-center py-8 text-gray-400">
                <FolderOpen className="w-6 h-6 mx-auto mb-2 opacity-50" />
                <p className="text-xs">Vault is empty</p>
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

          {/* Right panel: tabs + file viewer */}
          <div data-testid="vault-file-content" className="flex-1 flex flex-col min-w-0">
            <div className="px-6 pt-3 pb-2 shrink-0 flex items-center justify-end">
              <ViewModeTabs
                current={viewMode}
                onChange={setViewMode}
                className="bg-gray-100 dark:bg-gray-800"
              />
            </div>
            <div className="flex-1 overflow-y-auto px-6 pb-6 scrollbar-thin">
            {!selectedPath && (
              <div className="flex items-center justify-center h-full text-gray-400">
                <div className="text-center">
                  <FolderOpen className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">Select a file to view its contents</p>
                </div>
              </div>
            )}
            {selectedPath && fileLoading && (
              <p className="text-sm text-gray-400">Loading...</p>
            )}
            {selectedPath && !fileLoading && fileContent !== null && (
              <div>
                {/* Header: path + view toggle */}
                <div className="flex items-center justify-between mb-4 pb-2 border-b border-gray-200 dark:border-gray-700">
                  <p className="text-xs text-gray-400 font-mono truncate">{selectedPath}</p>
                  <button
                    onClick={() => setRawMode((r) => !r)}
                    className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 shrink-0 ml-3"
                    title={rawMode ? "Rendered view" : "Raw view"}
                  >
                    {rawMode ? (
                      <>
                        <Eye className="w-3.5 h-3.5" />
                        <span>Rendered</span>
                      </>
                    ) : (
                      <>
                        <Code className="w-3.5 h-3.5" />
                        <span>Raw</span>
                      </>
                    )}
                  </button>
                </div>

                {rawMode ? (
                  <pre data-testid="vault-raw-content" className="text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded-lg p-4 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                    {fileContent}
                  </pre>
                ) : (
                  <div>
                    {/* Frontmatter metadata block */}
                    {parsed && parsed.meta.length > 0 && (
                      <div className="mb-4 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
                        <table className="w-full text-xs">
                          <tbody>
                            {parsed.meta.map(({ key, value }, i) => (
                              <tr
                                key={i}
                                className={
                                  i % 2 === 0
                                    ? "bg-gray-50 dark:bg-gray-800/50"
                                    : "bg-white dark:bg-gray-800"
                                }
                              >
                                <td className="px-3 py-1.5 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap w-1/4">
                                  {key}
                                </td>
                                <td className="px-3 py-1.5 text-gray-700 dark:text-gray-300 font-mono break-all">
                                  {value}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Markdown body */}
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkObsidian, remarkWikiLink]}
                        rehypePlugins={[rehypeRaw, [rehypeSanitize, { ...defaultSchema, attributes: { ...defaultSchema.attributes, "*": [...(defaultSchema.attributes?.["*"] || []), "className"] } }]]}
                        components={markdownComponents}
                      >
                        {parsed?.body ?? fileContent}
                      </ReactMarkdown>
                    </div>
                  </div>
                )}

                {/* Backlinks panel */}
                <BacklinksPanel backlinks={backlinks} onNavigate={handleSelectFile} />
              </div>
            )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
