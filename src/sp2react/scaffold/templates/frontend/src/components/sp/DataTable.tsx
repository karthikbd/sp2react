import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  className?: string;
}

export function DataTable<T extends Record<string, any>>({ columns, rows, empty, className = "db-table", id, loading }: {
  columns: Column<T>[];
  rows: T[] | null;
  empty: ReactNode;
  className?: string;
  id?: string;
  loading?: ReactNode;
}) {
  return (
    <table className={className} id={id}>
      <thead>
        <tr>{columns.map((c) => <th key={c.key} className={c.className}>{c.header}</th>)}</tr>
      </thead>
      <tbody>
        {rows === null ? (
          <tr><td colSpan={columns.length}>{loading ?? "Loading..."}</td></tr>
        ) : rows.length === 0 ? (
          <tr><td colSpan={columns.length}>{empty}</td></tr>
        ) : (
          rows.map((r, i) => (
            <tr key={(r.ID as number) ?? i}>
              {columns.map((c) => <td key={c.key} className={c.className}>{c.render ? c.render(r) : String(r[c.key] ?? "")}</td>)}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
