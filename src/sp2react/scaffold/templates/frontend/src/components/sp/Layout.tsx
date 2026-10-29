// SharePoint 2013/2016 chrome: suite bar, site title, quick launch, page title area.
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, devUser, setDevUser } from "../../api";
import { useUser } from "../../runtime/user";
import { site } from "../../site";

function DevUserSwitch() {
  const { user, reload } = useUser();
  const [users, setUsers] = useState<{ login: string; title: string }[]>([]);
  useEffect(() => { api.users("").then(setUsers).catch(() => setUsers([])); }, []);
  if (!import.meta.env.DEV) return null;
  return (
    <label className="sp-devuser" title="Development only: act as another seeded user to test roles">
      Acting as{" "}
      <select value={devUser() ?? user?.login ?? ""} onChange={(e) => { setDevUser(e.target.value); reload(); window.location.reload(); }}>
        {users.map((u) => <option key={u.login} value={u.login}>{u.title}</option>)}
      </select>
    </label>
  );
}

export function Layout({ title, children }: { title: string; children: ReactNode }) {
  const { user, error } = useUser();
  const loc = useLocation();
  useEffect(() => { document.title = `${title} - ${site.title}`; }, [title]);
  return (
    <div className="sp-page">
      <div className="sp-suitebar">
        <span className="sp-brand">SharePoint</span>
        <span className="sp-suite-right">
          <DevUserSwitch />
          <span className="sp-username">{user?.title ?? (error ? "Not signed in" : "")}</span>
        </span>
      </div>
      <div className="sp-titlerow">
        <div className="sp-sitetitle"><Link to="/">{site.title}</Link></div>
        <h1 className="sp-pagetitle" id="pageTitle">{title}</h1>
      </div>
      <div className="sp-body">
        <nav className="sp-quicklaunch" aria-label="Quick launch">
          <ul>
            {site.quickLaunch.map((q) => (
              <li key={q.title} className={loc.pathname === q.href ? "selected" : ""}>
                {q.external ? <a href={q.href}>{q.title}</a> : <Link to={q.href}>{q.title}</Link>}
              </li>
            ))}
          </ul>
        </nav>
        <main className="sp-content">{error ? <div className="ms-formvalidation">{error}</div> : children}</main>
      </div>
    </div>
  );
}
