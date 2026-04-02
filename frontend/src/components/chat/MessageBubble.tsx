import Markdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../../api/types";
import { SourceCitation, extractWikilinks } from "./SourceCitation";
import { useMemo } from "react";

/** Allow inline code elements (used for wikilink pills) through sanitizer. */
const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "code"],
  attributes: {
    ...defaultSchema.attributes,
    code: [...(defaultSchema.attributes?.["code"] ?? []), "className"],
  },
};

interface MessageBubbleProps {
  message: ChatMessage;
}

/** Custom component to render wikilinks as emerald pill badges in markdown. */
function WikilinkRenderer({
  children,
  href,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
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
}

/** Render wikilink-pill badges inline via react-markdown components. */
function WikilinkPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="wikilink-pill inline-flex items-center px-2 py-0.5 rounded bg-accent-light/10 text-accent-light text-[12px] font-medium border border-accent-light/20 mx-0.5">
      {children}
    </span>
  );
}

/**
 * Transform [[wikilinks]] into markdown code spans with a wikilink: prefix
 * so they survive markdown parsing. The custom `code` component below
 * detects the prefix and renders them as pill badges.
 */
function transformWikilinks(text: string): string {
  return text.replace(
    /\[\[([^\]]+)\]\]/g,
    (_match, inner: string) => {
      const [target, alias] = inner.split("|");
      const display = (alias || target).trim();
      return `\`wikilink:${display}\``;
    },
  );
}

/** Custom code component that renders wikilink: prefixed code as pill badges. */
function CodeRenderer({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLElement>) {
  const text = typeof children === "string" ? children : String(children ?? "");
  if (!className && text.startsWith("wikilink:")) {
    return <WikilinkPill>{text.slice("wikilink:".length)}</WikilinkPill>;
  }
  return (
    <code className={className} {...props}>
      {children}
    </code>
  );
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const sources = useMemo(
    () => (isUser ? [] : extractWikilinks(message.content)),
    [isUser, message.content],
  );
  const transformedContent = useMemo(
    () => (isUser ? message.content : transformWikilinks(message.content)),
    [isUser, message.content],
  );

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} w-full`}>
      {isUser ? (
        <div className="max-w-2xl bg-surface-container-highest px-5 py-4 rounded-xl shadow-lg">
          <p
            data-testid="user-message"
            className="text-on-surface text-sm leading-relaxed whitespace-pre-wrap"
          >
            {message.content}
          </p>
        </div>
      ) : (
        <div className="max-w-3xl space-y-4">
          <div
            data-testid="assistant-message"
            className="bg-surface-container-low border border-outline-variant/20 p-6 rounded-xl relative"
          >
            <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-pre:my-2 text-on-surface-variant leading-relaxed">
              <Markdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[[rehypeSanitize, sanitizeSchema]]}
                components={{ a: WikilinkRenderer, code: CodeRenderer }}
              >
                {transformedContent}
              </Markdown>
            </div>
            <SourceCitation sources={sources} />
          </div>
        </div>
      )}
    </div>
  );
}
