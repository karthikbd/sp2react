// Types of the screen spec produced by sp2react (see sp2react/spec/model.py).
export type Mode = "new" | "edit" | "display";
export type Values = Record<string, any>;

export type Condition =
  | { all: Condition[] }
  | { any: Condition[] }
  | { not: Condition }
  | { role: string }
  | { mode: Mode | Mode[] }
  | ({ field: string } & Partial<Record<"eq" | "ne" | "gt" | "gte" | "lt" | "lte", unknown>> &
      Partial<Record<"in" | "nin", unknown[]>> & Partial<Record<"empty" | "notEmpty" | "changed", boolean>>);

export interface Field {
  name: string;
  label: string;
  type: "text" | "note" | "choice" | "multichoice" | "lookup" | "user" | "date" | "datetime" | "number" | "currency" | "boolean" | "url" | "calculated" | "taxonomy";
  required?: boolean;
  description?: string;
  max_length?: number;
  choices?: string[];
  format?: "dropdown" | "radio" | "checkboxes";
  fill_in?: boolean;
  lookup?: { list: string; field: string };
  multi?: boolean;
  min?: number;
  max?: number;
  lines?: number;
  read_only?: boolean;
  default?: unknown;
}

export interface Rule {
  id: string;
  kind: string;
  field?: string | null;
  list?: string | null;
  modes?: Mode[];
  when?: Condition | null;
  message?: string | null;
  presentation?: "inline" | "alert" | "banner" | "confirm";
  params?: Record<string, any>;
}

export interface Endpoint {
  id: string;
  method: string;
  path: string;
  purpose: string;
  list?: string | null;
  query?: Record<string, any>;
  roles?: string[];
}

export interface Component {
  id: string;
  kind: "form" | "tiles" | "table" | "list_view" | "banner" | "html" | "actions" | "custom";
  title?: string | null;
  region?: string | null;
  order?: number;
  data?: string[];
  props?: Record<string, any>;
  roles?: string[];
}

export interface ListSpec {
  title: string;
  primary?: boolean;
  fields: Field[];
  attachments?: boolean;
  views?: Record<string, { fields: string[]; title?: string; rowLimit?: number }>;
}

export interface Spec {
  version: number;
  screen: {
    id: string;
    kind: "list-form" | "page";
    title: string;
    route: string;
    legacy_urls: string[];
    list?: string | null;
    modes: Mode[];
    components: Component[];
  };
  lists: Record<string, ListSpec>;
  rules: Rule[];
  endpoints: Endpoint[];
  roles: string[];
}

export interface User {
  id: number;
  login: string;
  title: string;
  email?: string;
  groups: string[];
}

export function rulesForList(spec: Spec, list: string): Rule[] {
  return spec.rules.filter((r) => (r.list ?? spec.screen.list) === list);
}
