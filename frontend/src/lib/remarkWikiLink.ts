/**
 * Custom remark plugin to parse Obsidian-style wikilinks: [[target]] and [[target|display]].
 * Converts them into standard link nodes with a wikilink:// scheme for custom handling.
 */
import { visit } from "unist-util-visit";
import type { Plugin } from "unified";

interface TextNode {
  type: "text";
  value: string;
}

interface LinkNode {
  type: "link";
  url: string;
  children: TextNode[];
  data?: { hProperties?: Record<string, string> };
}

type MdastNode = TextNode | LinkNode | { type: string; children?: MdastNode[]; value?: string };

const WIKILINK_RE = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;

const remarkWikiLink: Plugin = () => {
  return (tree: MdastNode) => {
    visit(tree, "text", (node: TextNode, index: number | undefined, parent: MdastNode | undefined) => {
      if (index === undefined || !parent || !("children" in parent) || !parent.children) return;

      const matches: { start: number; end: number; target: string; display: string }[] = [];
      let match: RegExpExecArray | null;

      WIKILINK_RE.lastIndex = 0;
      while ((match = WIKILINK_RE.exec(node.value)) !== null) {
        matches.push({
          start: match.index,
          end: match.index + match[0].length,
          target: match[1].trim(),
          display: (match[2] || match[1]).trim(),
        });
      }

      if (matches.length === 0) return;

      const newNodes: MdastNode[] = [];
      let lastEnd = 0;

      for (const m of matches) {
        if (m.start > lastEnd) {
          newNodes.push({ type: "text", value: node.value.slice(lastEnd, m.start) });
        }
        newNodes.push({
          type: "link",
          url: `wikilink://${m.target}`,
          children: [{ type: "text", value: m.display }],
          data: { hProperties: { className: "wikilink" } },
        });
        lastEnd = m.end;
      }

      if (lastEnd < node.value.length) {
        newNodes.push({ type: "text", value: node.value.slice(lastEnd) });
      }

      parent.children.splice(index, 1, ...newNodes);
    });
  };
};

export default remarkWikiLink;
