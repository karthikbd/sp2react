// Old SharePoint URLs (bookmarks, emails, links in other sites) keep working:
// /sites/x/Lists/Y/EditForm.aspx?ID=3&Source=... -> /lists/y/edit/3?Source=...
import { Navigate, useLocation } from "react-router-dom";
import type { Spec } from "../runtime/spec";

export function LegacyRedirect({ specs }: { specs: Spec[] }) {
  const loc = useLocation();
  const path = decodeURIComponent(loc.pathname).toLowerCase();
  const q = new URLSearchParams(loc.search);
  for (const s of specs) {
    for (const u of s.screen.legacy_urls) {
      if (u.toLowerCase() !== path) continue;
      const file = u.split("/").pop()!.toLowerCase();
      const id = q.get("ID") ?? q.get("id");
      const src = q.get("Source");
      const keep = src ? `?Source=${encodeURIComponent(src.replace(/^https?:\/\/[^/]+/, ""))}` : "";
      if (s.screen.kind === "list-form") {
        if (file.startsWith("newform")) return <Navigate replace to={`${s.screen.route}/new${keep}`} />;
        if (file.startsWith("editform") && id) return <Navigate replace to={`${s.screen.route}/edit/${id}${keep}`} />;
        if (file.startsWith("dispform") && id) return <Navigate replace to={`${s.screen.route}/display/${id}${keep}`} />;
        return <Navigate replace to={s.screen.route} />;
      }
      return <Navigate replace to={s.screen.route} />;
    }
  }
  return <div className="sp-content"><h2>404 NOT FOUND</h2><p>Sorry, something went wrong. The page {loc.pathname} does not exist.</p></div>;
}
