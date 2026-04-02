import { KeyRound, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CredentialField } from "../../api/types";

interface SetupModalProps {
  entryName: string;
  onClose: () => void;
  onSuccess: () => void;
}

export function SetupModal({ entryName, onClose, onSuccess }: SetupModalProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [fields, setFields] = useState<CredentialField[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .credentialFields(entryName)
      .then((res) => {
        setFields(res.fields);
        const initial: Record<string, string> = {};
        for (const f of res.fields) {
          initial[f.name] = "";
        }
        setValues(initial);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [entryName]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setSaving(true);
      try {
        // Only send non-empty values
        const creds: Record<string, string> = {};
        for (const [k, v] of Object.entries(values)) {
          if (v.trim()) creds[k] = v.trim();
        }
        await api.storeCredentials(entryName, creds);
        onSuccess();
      } catch (err) {
        setError(String(err));
      } finally {
        setSaving(false);
      }
    },
    [entryName, values, onSuccess],
  );

  const requiredMissing = fields
    .filter((f) => f.required)
    .some((f) => !values[f.name]?.trim());

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-800 rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-full bg-accent/15">
              <KeyRound className="w-5 h-5 text-accent" />
            </div>
            <div>
              <h3 className="font-semibold text-gray-100">Setup Credentials</h3>
              <p className="text-sm text-gray-500">{entryName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-600 hover:text-gray-300"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {loading && (
          <p className="text-sm text-gray-600 py-4 text-center">Loading...</p>
        )}

        {!loading && fields.length === 0 && (
          <div>
            <p className="text-sm text-gray-500 mb-4">
              This entry has no credential fields to configure.
            </p>
            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm rounded-lg border border-gray-700 text-gray-300 hover:bg-gray-800 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        )}

        {!loading && fields.length > 0 && (
          <form onSubmit={handleSubmit}>
            <div className="space-y-3 mb-4">
              {fields.map((field) => (
                <div key={field.name}>
                  <label className="block text-xs font-medium text-gray-400 mb-1">
                    {field.description || field.name}
                    {field.required && <span className="text-red-400 ml-0.5">*</span>}
                  </label>
                  <input
                    type="password"
                    value={values[field.name] ?? ""}
                    onChange={(e) =>
                      setValues((prev) => ({ ...prev, [field.name]: e.target.value }))
                    }
                    required={field.required}
                    placeholder={field.name}
                    className="w-full rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                  />
                </div>
              ))}
            </div>

            {error && (
              <p className="text-xs text-red-400 mb-3">{error}</p>
            )}

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm rounded-lg border border-gray-700 text-gray-300 hover:bg-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving || requiredMissing}
                className="px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
