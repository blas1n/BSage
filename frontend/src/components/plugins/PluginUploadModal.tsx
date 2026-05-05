"use client";

import { useCallback, useRef, useState } from "react";
import { api } from "../../api/client";
import { useLatestImportProgress } from "../../hooks/useImportProgress";
import { ImportProgressBar } from "../imports/ImportProgressBar";
import { Icon } from "../common/Icon";

type Status = "idle" | "uploading" | "running" | "done" | "error";

export type SourceOption = { value: string; label: string; instructions: string };

export interface PluginUploadModalProps {
  /** Plugin name to invoke after upload completes (e.g. chatgpt-memory-input). */
  pluginName: string;
  /** Modal title shown to the user. */
  title: string;
  /** Short subtitle / accepted-file hint. */
  subtitle?: string;
  /** Comma-separated `accept` list for the file input. */
  accept?: string;
  /** Optional how-to-get-this-file instructions (markdown-ish plain text). */
  instructions?: string;
  /** Optional source picker. When provided, user picks one and it's
   *  forwarded to the plugin as input_data.source. The instructions
   *  block updates per selection. */
  sourceOptions?: SourceOption[];
  /** Closes the modal — caller controls visibility. */
  onClose: () => void;
  /** Optional callback fired once the plugin run completes. */
  onComplete?: (results: unknown[]) => void;
}

export function PluginUploadModal({
  pluginName,
  title,
  subtitle,
  accept,
  instructions,
  sourceOptions,
  onClose,
  onComplete,
}: PluginUploadModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string>("");
  const [source, setSource] = useState<string>(sourceOptions?.[0]?.value ?? "");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const sourceOption = sourceOptions?.find((o) => o.value === source);
  const helpText = sourceOption?.instructions ?? instructions;

  // Derived from the live WSEvent stream — null until a BATCH_START
  // arrives. Sticks around briefly after BATCH_COMPLETE so the modal can
  // show "32 notes created · 0 failed" before the user dismisses.
  const importProgress = useLatestImportProgress();

  const onPick = useCallback((picked: File | null) => {
    setFile(picked);
    setError(null);
    setStatus("idle");
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onPick(dropped);
  }, [onPick]);

  const submit = useCallback(async () => {
    if (!file) return;
    setError(null);
    setResult(null);
    try {
      setStatus("uploading");
      setProgress(`Uploading ${file.name}…`);
      const upload = await api.uploadFile(file);

      setStatus("running");
      setProgress(`Running ${pluginName}…`);
      const payload: Record<string, unknown> = {
        upload_id: upload.upload_id,
        path: upload.path,
        filename: upload.filename,
      };
      if (source) payload.source = source;
      const runResult = await api.runWithInput(pluginName, payload);

      // Surface plugin's own structured result so users can see what happened.
      // PluginRunner returns results: list[dict]; the first item is the plugin
      // execute() return value when produced via on_demand triggering.
      const first = Array.isArray(runResult.results) && runResult.results.length > 0
        ? (runResult.results[0] as Record<string, unknown>)
        : {};
      setResult(first);

      // Plugin-reported error (e.g. "no input file provided") is success at the
      // HTTP layer but a failure semantically — show it as such.
      if (typeof first.error === "string") {
        setStatus("error");
        setError(first.error);
      } else {
        setStatus("done");
      }
      setProgress("");
      onComplete?.(runResult.results);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [file, pluginName, source, onComplete]);

  const busy = status === "uploading" || status === "running";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur p-4"
      onClick={busy ? undefined : onClose}
    >
      <div
        className="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-xl bg-surface border border-white/10 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="font-headline font-bold text-on-surface">{title}</h2>
            {subtitle && (
              <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
            )}
          </div>
          <button
            onClick={onClose}
            disabled={busy}
            className="text-gray-500 hover:text-gray-300 disabled:opacity-40"
            aria-label="Close"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {sourceOptions && sourceOptions.length > 0 && (
          <div className="mb-4">
            <div className="text-[11px] font-medium text-gray-400 mb-2">Source</div>
            <div className="flex flex-wrap gap-1.5">
              {sourceOptions.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSource(opt.value)}
                  className={`min-h-10 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                    source === opt.value
                      ? "bg-accent-light/20 text-accent-light"
                      : "text-gray-400 hover:bg-white/5"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {helpText && (
          <details className="mb-4 group" open>
            <summary className="cursor-pointer text-[11px] text-accent-light hover:underline list-none flex items-center gap-1">
              <Icon name="help_outline" size={12} />
              <span>How to get this file</span>
            </summary>
            <pre className="text-[10px] font-mono text-gray-300 bg-gray-850 border border-gray-700 rounded-lg p-3 mt-2 whitespace-pre-wrap">
              {helpText}
            </pre>
          </details>
        )}

        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          onClick={() => !busy && inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
            file ? "border-accent-light/40 bg-accent-light/5" : "border-white/10 hover:border-white/20"
          } ${busy ? "pointer-events-none opacity-60" : ""}`}
        >
          <Icon
            name={file ? "description" : "upload_file"}
            className="mx-auto mb-2 text-gray-400"
            size={32}
          />
          {file ? (
            <>
              <p className="text-sm text-on-surface truncate">{file.name}</p>
              <p className="text-[10px] text-gray-500 mt-1">
                {(file.size / 1024).toFixed(1)} KB
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-gray-300">Drop file here or click to choose</p>
              {accept && (
                <p className="text-[10px] text-gray-500 mt-1">Accepted: {accept}</p>
              )}
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            className="hidden"
            onChange={(e) => onPick(e.target.files?.[0] ?? null)}
          />
        </div>

        {/* Upload progress text — only shown during the upload step. Once
            we hit "running" the live ImportProgressBar takes over below. */}
        {progress && status === "uploading" && (
          <p className="text-xs text-gray-400 mt-4 font-mono">{progress}</p>
        )}
        {/* Live compile progress: appears as soon as the backend emits
            INGEST_COMPILE_BATCH_START and stays through completion. */}
        {status === "running" && importProgress && (
          <ImportProgressBar progress={importProgress} />
        )}
        {/* Fallback for the brief window between "uploading" finishing and
            the first BATCH_START arriving. */}
        {status === "running" && !importProgress && (
          <p className="text-xs text-gray-400 mt-4 font-mono">{progress}</p>
        )}
        {error && (
          <div className="mt-4 px-3 py-2 rounded-lg border border-red-400/30 bg-red-400/10 text-xs text-red-300 break-words">
            {error}
          </div>
        )}
        {status === "done" && (
          <div className="mt-4 px-3 py-2 rounded-lg border border-accent-light/30 bg-accent-light/10 text-xs text-accent-light">
            <div className="font-bold mb-0.5">Import complete</div>
            {result && typeof result.imported === "number" && (
              <div className="text-[10px] opacity-80 font-mono">
                {result.imported} note{result.imported === 1 ? "" : "s"} written
                {typeof result.source === "string" && ` · source=${result.source}`}
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-sm text-gray-300 hover:bg-white/5 disabled:opacity-40"
          >
            {status === "done" ? "Close" : "Cancel"}
          </button>
          {status !== "done" && (
            <button
              onClick={submit}
              disabled={!file || busy}
              className="px-4 py-2 rounded-lg bg-accent-light text-gray-950 font-bold text-sm disabled:opacity-40"
            >
              {busy ? "Working…" : "Import"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
