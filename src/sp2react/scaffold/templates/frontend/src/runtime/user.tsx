import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { User } from "./spec";

const Ctx = createContext<{ user: User | null; error: string | null; reload: () => void }>({ user: null, error: null, reload: () => {} });

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    api.me().then((u) => { setUser(u); setError(null); }).catch((e) => setError(e.message));
  }, [n]);
  return <Ctx.Provider value={{ user, error, reload: () => setN((x) => x + 1) }}>{children}</Ctx.Provider>;
}

export const useUser = () => useContext(Ctx);

export function inGroup(user: User | null, group: string): boolean {
  return !!user && user.groups.includes(group);
}
