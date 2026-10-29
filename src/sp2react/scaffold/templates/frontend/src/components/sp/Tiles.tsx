import type { ReactNode } from "react";

export interface Tile {
  id?: string;
  label: string;
  value: ReactNode;
  alert?: boolean;
}

export function Tiles({ tiles, className = "db-tiles" }: { tiles: Tile[]; className?: string }) {
  return (
    <div className={className}>
      {tiles.map((t, i) => (
        <div key={t.id ?? i} id={t.id} className={`db-tile${t.alert ? " db-alert" : ""}`}>
          <span className="db-count">{t.value}</span>
          {t.label}
        </div>
      ))}
    </div>
  );
}
