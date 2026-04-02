import { ChevronDown, ChevronRight, FileText, Folder } from "lucide-react";
import { useCallback, useState } from "react";
import type { VaultTreeEntry } from "../../api/types";

interface DirectoryTreeProps {
  tree: VaultTreeEntry[];
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
  filterPaths?: Set<string> | null;
}

/** Check if a directory contains any file matching the filter. */
function dirHasFilteredFiles(
  path: string,
  entryMap: Map<string, VaultTreeEntry>,
  filterPaths: Set<string>,
): boolean {
  const entry = entryMap.get(path);
  if (!entry) return false;
  for (const file of entry.files) {
    const filePath = path ? `${path}/${file}` : file;
    if (filterPaths.has(filePath)) return true;
  }
  for (const dir of entry.dirs) {
    const dirPath = path ? `${path}/${dir}` : dir;
    if (dirHasFilteredFiles(dirPath, entryMap, filterPaths)) return true;
  }
  return false;
}

export function DirectoryTree({ tree, selectedPath, onSelectFile, filterPaths }: DirectoryTreeProps) {
  const entryMap = new Map<string, VaultTreeEntry>();
  for (const entry of tree) {
    entryMap.set(entry.path, entry);
  }

  const root = entryMap.get("");
  if (!root) return null;

  return (
    <div className="text-sm select-none">
      {root.dirs.map((dir, i) => {
        if (filterPaths && !dirHasFilteredFiles(dir, entryMap, filterPaths)) return null;
        return (
          <DirNode
            key={dir}
            name={dir}
            path={dir}
            depth={0}
            isLast={i === root.dirs.length - 1 && root.files.length === 0}
            entryMap={entryMap}
            selectedPath={selectedPath}
            onSelectFile={onSelectFile}
            filterPaths={filterPaths}
            defaultOpen
          />
        );
      })}
      {root.files.map((file, i) => {
        if (filterPaths && !filterPaths.has(file)) return null;
        return (
          <FileNode
            key={file}
            name={file}
            path={file}
            depth={0}
            isLast={i === root.files.length - 1}
            selected={selectedPath === file}
            onSelect={onSelectFile}
          />
        );
      })}
    </div>
  );
}

function TreeIndent({ depth, isLast }: { depth: number; isLast: boolean }) {
  if (depth === 0) return null;
  return (
    <span className="inline-flex shrink-0" aria-hidden>
      {Array.from({ length: depth - 1 }, (_, i) => (
        <span key={i} className="inline-block w-4 border-l border-gray-700" />
      ))}
      <span
        className={`inline-block w-4 border-l border-gray-700 ${
          isLast ? "h-1/2 self-start" : ""
        }`}
      />
      <span className="inline-block w-2 border-b border-gray-700 self-center" />
    </span>
  );
}

function DirNode({
  name,
  path,
  depth,
  isLast,
  entryMap,
  selectedPath,
  onSelectFile,
  filterPaths,
  defaultOpen = false,
}: {
  name: string;
  path: string;
  depth: number;
  isLast: boolean;
  entryMap: Map<string, VaultTreeEntry>;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
  filterPaths?: Set<string> | null;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const toggle = useCallback(() => setOpen((o) => !o), []);

  const entry = entryMap.get(path);
  const childDirs = entry?.dirs ?? [];
  const childFiles = entry?.files ?? [];

  // Filter children
  const visibleDirs = filterPaths
    ? childDirs.filter((dir) =>
        dirHasFilteredFiles(path ? `${path}/${dir}` : dir, entryMap, filterPaths),
      )
    : childDirs;
  const visibleFiles = filterPaths
    ? childFiles.filter((file) => {
        const filePath = path ? `${path}/${file}` : file;
        return filterPaths.has(filePath);
      })
    : childFiles;

  const totalVisible = visibleDirs.length + visibleFiles.length;

  return (
    <div>
      <button
        onClick={toggle}
        className="flex items-center w-full py-0.5 text-left text-gray-300 hover:bg-gray-800/50 rounded transition-colors"
      >
        <TreeIndent depth={depth} isLast={isLast} />
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-500 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-500 shrink-0" />
        )}
        <Folder className="w-3.5 h-3.5 text-amber-500 shrink-0" style={{ margin: "0 0.25rem" }} />
        <span className="truncate text-xs font-medium">{name}</span>
      </button>
      {open && totalVisible > 0 && (
        <div>
          {visibleDirs.map((dir, i) => (
            <DirNode
              key={dir}
              name={dir}
              path={path ? `${path}/${dir}` : dir}
              depth={depth + 1}
              isLast={i === visibleDirs.length - 1 && visibleFiles.length === 0}
              entryMap={entryMap}
              selectedPath={selectedPath}
              onSelectFile={onSelectFile}
              filterPaths={filterPaths}
            />
          ))}
          {visibleFiles.map((file, i) => {
            const filePath = path ? `${path}/${file}` : file;
            return (
              <FileNode
                key={file}
                name={file}
                path={filePath}
                depth={depth + 1}
                isLast={i === visibleFiles.length - 1}
                selected={selectedPath === filePath}
                onSelect={onSelectFile}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function FileNode({
  name,
  path,
  depth,
  isLast,
  selected,
  onSelect,
}: {
  name: string;
  path: string;
  depth: number;
  isLast: boolean;
  selected: boolean;
  onSelect: (path: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(path)}
      className={`flex items-center w-full py-0.5 text-left rounded transition-colors text-xs ${
        selected
          ? "bg-accent/15 text-accent-light"
          : "text-gray-400 hover:bg-gray-800/50"
      }`}
    >
      <TreeIndent depth={depth} isLast={isLast} />
      <FileText className="w-3.5 h-3.5 shrink-0" style={{ margin: "0 0.25rem" }} />
      <span className="truncate">{name}</span>
    </button>
  );
}
