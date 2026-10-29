// Fallback renderer for a page screen before (or without) an agent-written Page.tsx:
// shows the authored HTML fragments, list views and banners from the spec in region order.
import { Layout } from "./Layout";
import { LegacyHtml } from "./LegacyHtml";
import { ListView, parseViewXml } from "./ListView";
import { Banner } from "./Banner";
import type { Spec } from "../../runtime/spec";

export function GenericPage({ spec }: { spec: Spec }) {
  const comps = [...spec.screen.components].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  return (
    <Layout title={spec.screen.title}>
      {comps.map((c) => {
        if (c.kind === "html") return <LegacyHtml key={c.id} html={c.props?.legacy_html ?? ""} />;
        if (c.kind === "banner") return <Banner key={c.id} text={c.props?.text ?? ""} tone={c.props?.tone ?? "info"} />;
        if (c.kind === "list_view") {
          const list = c.props?.list as string;
          const lst = spec.lists[list];
          if (!lst) return null;
          const v = parseViewXml(c.props?.view_xml);
          return <ListView key={c.id} list={list} fields={lst.fields} title={c.title} showNew={false}
                           view={{ fields: v.fields ?? lst.fields.slice(0, 4).map((f) => f.name), orderby: v.orderby, top: v.top }} />;
        }
        return null;
      })}
    </Layout>
  );
}
