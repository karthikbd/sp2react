// Static markup authored in Script Editor / Content Editor web parts (help text, instructions).
// It is rebuilt from an allow-list of tags and attributes (runtime/sanitize.ts), so scripts, event handlers,
// svg and javascript: links cannot reach the page however they are written.
import { sanitizeHtml } from "../../runtime/sanitize";

export function LegacyHtml({ html, className }: { html: string; className?: string }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }} />;
}
