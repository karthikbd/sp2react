// Static markup authored in Script Editor / Content Editor web parts (help text, instructions).
// Scripts were removed during analysis; event handlers and javascript: URLs are stripped here too.
export function LegacyHtml({ html, className }: { html: string; className?: string }) {
  const safe = html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, "")
    .replace(/(href|src)\s*=\s*(["'])\s*javascript:[^"']*\2/gi, "");
  return <div className={className} dangerouslySetInnerHTML={{ __html: safe }} />;
}
