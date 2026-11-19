"""Where the generated app's own code runs: its back-end tests (test stage) and its loader (reconcile).

That code includes handlers written by AI agents and not yet reviewed, so it never runs as plain host code:

- ``container``: in a throwaway Docker or Podman container: no network (or, with ``data_source: database``,
  only the database host), a read-only file system except the folders the step writes, no Linux
  capabilities, a process and memory limit, none of the host's environment, and the guard below inside it;
- ``guard``: on this machine, under ``sandbox_guard.py`` (an audit hook that refuses writes outside those
  folders, new processes, other network hosts and native code), with sp2react's credentials removed from
  the environment; defence in depth, not isolation;
- ``auto`` (default): ``container`` when Docker or Podman answers, otherwise ``guard``;
- ``off``: plain host processes (credentials still removed). Not recommended.

Front-end checks (npm install, tsc, vite build, the rule vectors) run template code only: agent-written
TypeScript is type-checked and bundled, never executed, so they stay on the host.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

GUARD = Path(__file__).with_name("sandbox_guard.py")
DOCKERFILE = Path(__file__).parent / "container" / "Dockerfile"
HIDDEN_ENV: set[str] = set()   # names of sp2react's own secrets; set by the pipeline from the config
PASS_ENV = ("PATH", "SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
            "LANG", "LC_ALL", "TZ", "NODE_OPTIONS", "NPM_CONFIG_REGISTRY", "npm_config_registry",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
            "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "PIP_INDEX_URL", "PIP_CERT")


def app_env(extra: Optional[dict[str, Any]] = None, hide: Iterable[str] = ()) -> dict[str, str]:
    """The environment for the generated app's processes: this process's environment without sp2react's
    own credentials (SharePoint, model, database URL variable), plus `extra`."""
    drop = {n for n in (*HIDDEN_ENV, *hide) if n}
    return {**{k: v for k, v in os.environ.items() if k not in drop}, **{k: str(v) for k, v in (extra or {}).items()}}


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


def run_process(cmd: list[str], cwd: Path, timeout: int, env: dict[str, str],
                on_timeout: Optional[Callable[[], None]] = None) -> Result:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)  # noqa: S603
        return Result(r.returncode, r.stdout or "", r.stderr or "")
    except subprocess.TimeoutExpired as e:
        if on_timeout:
            on_timeout()
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")   # bytes even with text=True
        return Result(124, out, f"timed out after {timeout}s: {' '.join(cmd)}\n")
    except FileNotFoundError as e:
        return Result(127, "", str(e))


def container_runtime() -> Optional[str]:
    """Podman or Docker, if installed and its daemon or machine answers."""
    for name in ("podman", "docker"):
        path = shutil.which(name)
        if path and run_process([path, "info"], Path.cwd(), 30, app_env()).code == 0:
            return path
    return None


def db_extras(env: dict[str, Any]) -> tuple[str, bool]:
    """pip packages and whether the Microsoft ODBC driver are needed for the database URL the app gets."""
    url = str(env.get("DB_URL") or "")
    scheme = url.split(":", 1)[0].lower()
    if "pymysql" in scheme:
        return "pymysql>=1.1.1", False
    if "pyodbc" in scheme:
        return "pyodbc>=5.0", True
    if "psycopg" in scheme or scheme.startswith("postgres"):
        return "psycopg[binary]>=3.1", False
    return "", False


@dataclass
class Sandbox:
    mode: str = "auto"                       # auto | container | guard | off
    image: Optional[str] = None              # a prebuilt check image; otherwise built from container/Dockerfile
    hosts: list[str] = field(default_factory=list)   # network hosts the generated code may reach (the database)
    data: list[Path] = field(default_factory=list)   # folders it may also write: a file database (sqlite:///...)
    progress: Callable[[str], None] = lambda s: None
    _runtime: Optional[str] = None
    _resolved: Optional[str] = None
    note: str = ""

    def resolve(self) -> str:
        if self._resolved:
            return self._resolved
        if self.mode in ("guard", "off"):
            self._resolved = self.mode
        else:
            self._runtime = container_runtime()
            if self._runtime:
                self._resolved = "container"
            elif self.mode == "container":
                raise RuntimeError("pipeline.sandbox is 'container' but neither Podman nor Docker answers; "
                                   "start one, or set pipeline.sandbox: guard")
            else:
                self._resolved = "guard"
                self.note = "no Docker or Podman found: generated code runs under the guard on this machine"
        return self._resolved

    # ---------------------------------------------------------------- run
    def python(self, args: list[str], cwd: Path, env: dict[str, Any], write: list[Path], read: list[Path],
               timeout: int = 900) -> Result:
        """Run `python <args>` for the generated app. `write` are the only folders it may change; `read` are
        extra folders it needs to see (in a container nothing else of this machine is visible)."""
        mode = self.resolve()
        write = [*write, *self.data]
        if mode == "container":
            res = self._container(args, cwd, env, write, read, timeout)
            if res is not None:
                return res
            mode = "guard"
        with tempfile.TemporaryDirectory(prefix="sp2react-sandbox-") as tmp:    # its own temp folder, not the shared one
            guard_env = {"SP2REACT_GUARD_WRITE": os.pathsep.join(str(p) for p in write),
                         "SP2REACT_GUARD_HOSTS": ",".join(self.hosts), "PYTHONDONTWRITEBYTECODE": "1",
                         "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp}
            cmd = [sys.executable, *(([str(GUARD)]) if mode == "guard" else []), *args]
            return run_process(cmd, cwd, timeout, app_env({**env, **guard_env}))

    # ----------------------------------------------------------- container
    def _image(self, backend: Path, env: dict[str, Any]) -> Optional[str]:
        if self.image:
            return self.image
        assert self._runtime is not None  # noqa: S101  resolve() found it
        extra, mssql = db_extras(env)
        req = (backend / "requirements.txt").read_bytes() if (backend / "requirements.txt").exists() else b""
        digest = hashlib.sha256(DOCKERFILE.read_bytes() + req + extra.encode() + bytes([mssql])).hexdigest()[:12]
        tag = f"sp2react-checks:{digest}"
        if run_process([self._runtime, "image", "inspect", tag], backend, 60, app_env()).code == 0:
            return tag
        self.progress(f"[sandbox] building the check image {tag} (once per requirements change)")
        build = run_process([self._runtime, "build", "-f", str(DOCKERFILE), "--build-arg", f"EXTRA_PIP={extra}",
                             "--build-arg", f"MSSQL={int(mssql)}", "-t", tag, str(backend)], backend, 1800, app_env())
        if build.code != 0:
            if self.mode == "container":
                raise RuntimeError(f"could not build the check image:\n{build.output[-3000:]}")
            self.note = f"the check image could not be built, so generated code ran under the guard: {build.output[-400:]}"
            self._resolved = "guard"
            self.progress(f"[sandbox] {self.note}")
            return None
        return tag

    def _container(self, args: list[str], cwd: Path, env: dict[str, Any], write: list[Path], read: list[Path],
                   timeout: int) -> Optional[Result]:
        rt = self._runtime
        assert rt is not None  # noqa: S101
        backend = cwd if (cwd / "requirements.txt").exists() else next((p for p in read if (p / "backend").is_dir()), cwd) / "backend"
        image = self._image(backend, env)
        if image is None:
            return None
        # the app keeps its layout (backend/../shared); folders it may write are mounted over it, writable
        mounts: list[tuple[Path, str, bool]] = []
        for i, p in enumerate(read):
            mounts.append((p.resolve(), "/work/app" if i == 0 else f"/work/r{i}", False))
        for i, p in enumerate(write):
            host = p.resolve()
            under = next(((h, t) for h, t, rw in mounts if not rw and (host == h or h in host.parents)), None)
            mounts.append((host, under[1] + "/" + host.relative_to(under[0]).as_posix() if under else f"/work/w{i}", True))

        def inside(value: str) -> str:       # host paths -> container paths, longest mount first
            for host, target, _ in sorted(mounts, key=lambda m: -len(str(m[0]))):
                h = str(host)
                if value == h or value.startswith(h + os.sep):
                    return target + value[len(h):].replace(os.sep, "/")
            return value

        name = f"sp2react-check-{uuid.uuid4().hex[:12]}"
        cmd = [rt, "run", "--rm", "--name", name, "--read-only", "--tmpfs", "/tmp:rw,size=1g",  # noqa: S108  the container's own tmpfs
               "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "512", "--memory", "4g",
               "--network", "host" if self.hosts else "none"]
        if "podman" in Path(rt).name:
            cmd += ["--userns", "keep-id"]       # rootless: this user's id is the same inside
        if hasattr(os, "getuid"):
            cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]   # files it writes stay yours
        for host, target, rw in sorted(mounts, key=lambda m: m[1].count("/")):   # parents before the folders inside them
            cmd += ["-v", f"{host}:{target}:{'rw' if rw else 'ro'}"]
        cmd += ["-v", f"{GUARD}:/sp2react/guard.py:ro"]
        guard_env = {"SP2REACT_GUARD_WRITE": ":".join(inside(str(p.resolve())) for p in write),
                     "SP2REACT_GUARD_HOSTS": ",".join(self.hosts), "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"}  # noqa: S108
        def url_inside(url: str) -> str:     # sqlite:////host/path/db -> sqlite:////work/..; server URLs unchanged
            if url.startswith("sqlite:///") and len(url) > len("sqlite:///"):
                return "sqlite:///" + inside(url[len("sqlite:///"):])
            return url

        for k, v in {**{k: str(v) for k, v in env.items()}, **guard_env}.items():
            cmd += ["-e", f"{k}={url_inside(v) if k == 'DB_URL' else inside(v)}"]
        cmd += ["-w", inside(str(cwd.resolve())), image, "python", "/sp2react/guard.py",
                *[inside(a) for a in args]]

        def stop() -> None:                  # a timed-out client must not leave the container running
            run_process([rt, "kill", name], cwd, 60, app_env())

        res = run_process(cmd, cwd, timeout, app_env(), on_timeout=stop)
        res.stderr = res.stderr + ("" if res.code == 0 else f"\n[sandbox: container {image}]")
        return res

    def describe(self) -> str:
        mode = self.resolve()
        return f"sandbox: {mode}" + (f" ({self.note})" if self.note else "")
