// Routes for one list's forms: AllItems, NewForm, EditForm, DispForm.
import { Route, Routes, useParams } from "react-router-dom";
import { Layout } from "../components/sp/Layout";
import { ListForm } from "../components/sp/Form";
import { ListView } from "../components/sp/ListView";
import type { Mode, Spec } from "../runtime/spec";

function FormRoute({ spec, mode }: { spec: Spec; mode: Mode }) {
  const { id } = useParams();
  const list = spec.lists[spec.screen.list as string];
  const suffix = mode === "new" ? "New Item" : list.title;
  return (
    <Layout title={mode === "new" ? `${list.title} - ${suffix}` : list.title}>
      <ListForm key={`${mode}-${id ?? ""}`} spec={spec} mode={mode} id={id} />
    </Layout>
  );
}

export function ListFormScreen({ spec }: { spec: Spec }) {
  const listName = spec.screen.list as string;
  const list = spec.lists[listName];
  const views = list.views ?? {};
  const v = views.AllItems ?? Object.values(views)[0];
  const view = { fields: v?.fields?.length ? v.fields : list.fields.slice(0, 6).map((f) => f.name), orderby: "ID desc", top: v?.rowLimit ?? 30 };
  return (
    <Routes>
      <Route index element={<Layout title={list.title}><ListView list={listName} fields={list.fields} view={view} route={spec.screen.route} /></Layout>} />
      {spec.screen.modes.includes("new") && <Route path="new" element={<FormRoute spec={spec} mode="new" />} />}
      {spec.screen.modes.includes("edit") && <Route path="edit/:id" element={<FormRoute spec={spec} mode="edit" />} />}
      {spec.screen.modes.includes("display") && <Route path="display/:id" element={<FormRoute spec={spec} mode="display" />} />}
    </Routes>
  );
}
