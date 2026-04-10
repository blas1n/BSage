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
