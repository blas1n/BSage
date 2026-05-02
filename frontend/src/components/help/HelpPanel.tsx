import { useTranslation } from "react-i18next";

interface HelpSection {
  titleKey: string;
  descriptionKey: string;
  docLink?: string;
}

const HELP_CONTENT: Record<string, HelpSection> = {
  "#chat": {
    titleKey: "nav.currentChat",
    descriptionKey: "help.section.chat",
    docLink: "https://bsvibe.dev/bsage/getting-started",
  },
  "#graph": {
    titleKey: "nav.knowledgeBase",
    descriptionKey: "help.section.graph",
  },
  "#plugins": {
    titleKey: "plugins.title",
    descriptionKey: "help.section.plugins",
    docLink: "https://bsvibe.dev/bsage/features/plugins",
  },
  "#vault": {
    titleKey: "nav.vaultBrowser",
    descriptionKey: "help.section.vault",
  },
  "#dashboard": {
    titleKey: "dashboard.title",
    descriptionKey: "help.section.dashboard",
  },
};

const DEFAULT_HELP: HelpSection = {
  titleKey: "help.title",
  descriptionKey: "help.section.default",
};

interface HelpPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function HelpPanel({ isOpen, onClose }: HelpPanelProps) {
  const { t } = useTranslation();
  const hash = typeof window !== "undefined" ? window.location.hash || "" : "";
  const section = HELP_CONTENT[hash] ?? DEFAULT_HELP;

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40"
          onClick={onClose}
        />
      )}
      <div
        className={`fixed top-0 right-0 h-full w-80 bg-gray-900 border-l border-gray-700 text-gray-50 z-50 shadow-xl transform transition-transform duration-200 ease-in-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-emerald-400">{t("help.panelTitle")}</h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-800 text-gray-400 hover:text-gray-50 transition-colors"
            aria-label={t("help.closePanelAria")}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <h3 className="text-base font-medium text-emerald-400 mb-1">
              {t(section.titleKey)}
            </h3>
            <p className="text-sm text-gray-300 leading-relaxed">
              {t(section.descriptionKey)}
            </p>
          </div>

          {section.docLink && (
            <a
              href={section.docLink}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300 transition-colors"
            >
              <span>{t("help.viewDocs")}</span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-4 w-4"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z" />
                <path d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z" />
              </svg>
            </a>
          )}
        </div>
      </div>
    </>
  );
}
