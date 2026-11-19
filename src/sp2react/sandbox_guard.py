"""Run a Python program with sp2react's guard: the generated app's tests and loader run under it.

Usage (standard library only, so it also runs inside the check container where sp2react isn't installed):

    python sandbox_guard.py -m pytest -q tests
    python sandbox_guard.py -c "code" arg1 arg2
    python sandbox_guard.py script.py arg1

The generated back end imports handlers written by AI agents, so its tests run code nobody has reviewed yet.
Before that code is imported, this installs a PEP 578 audit hook that refuses:

- writing, deleting, renaming or creating files outside SP2REACT_GUARD_WRITE (os.pathsep-separated folders) and
  the temporary folder; SQLite databases count as writes;
- starting processes (subprocess, os.system, exec, spawn, fork, posix_spawn, Windows CreateProcess);
- network connections other than loopback and the hosts in SP2REACT_GUARD_HOSTS (comma-separated; the
  database server in data_source: database);
- loading native code through ctypes, and walking the object graph through gc (ways around the rules above).

An audit hook cannot be removed once installed. It is defence in depth, not isolation: CPython's audit hooks are
not designed as a security boundary. For isolation, sp2react runs this same guard inside a container
(pipeline.sandbox: container, or auto when Docker or Podman is available).
"""
from __future__ import annotations

import ipaddress
import os
import runpy
import socket
import sys
import tempfile
from typing import Any, NoReturn

PREFIX = "sp2react sandbox"

PROCESS_EVENTS = {
    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
    "os.startfile", "pty.spawn", "_winapi.CreateProcess", "os.kill", "os.killpg", "signal.pthread_kill",
}
ESCAPE_EVENTS = {
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.cdata", "ctypes.cdata/buffer", "ctypes.call_function",
    "ctypes.get_errno", "ctypes.set_errno", "ctypes.string_at", "ctypes.wstring_at", "ctypes.addressof",
    "gc.get_referrers", "gc.get_referents", "gc.get_objects",
}
PATH_EVENTS = {          # event -> (path argument, its dir_fd argument or None) for each path it writes
    "os.remove": ((0, 1),), "os.rmdir": ((0, 1),), "os.mkdir": ((0, 2),), "os.rename": ((0, 2), (1, 3)),
    "os.symlink": ((1, 2),), "os.link": ((1, 3),), "os.truncate": ((0, None),), "os.chmod": ((0, 2),),
    "os.chown": ((0, 3),), "os.utime": ((0, 3),), "os.chflags": ((0, None),), "os.lchflags": ((0, None),),
    "os.setxattr": ((0, None),), "os.removexattr": ((0, None),), "shutil.rmtree": ((0, 1),),
    "shutil.copyfile": ((1, None),), "shutil.copymode": ((1, None),), "shutil.copystat": ((1, None),),
    "shutil.copytree": ((1, None),), "shutil.move": ((0, None), (1, None)), "shutil.make_archive": ((0, None),),
    "shutil.unpack_archive": ((1, None),),
}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def fd_path(fd: int) -> "str | None":
    """The path an open directory descriptor points to, where the OS can tell (Linux, macOS)."""
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        pass
    try:
        import fcntl
        return os.fsdecode(fcntl.fcntl(fd, 50, b"\0" * 1024).split(b"\0", 1)[0])   # F_GETPATH (macOS)
    except (ImportError, OSError, ValueError):
        return None


class Guard:
    def __init__(self, write_roots: list[str], hosts: list[str]) -> None:
        self.roots = [os.path.realpath(r) for r in [*write_roots, tempfile.gettempdir()] if r]
        self.hosts = {h.strip().lower() for h in hosts if h.strip()}
        self.ips: set[str] = set()
        for h in self.hosts:              # resolved now, before the hook exists
            try:
                self.ips.update(str(ai[4][0]) for ai in socket.getaddrinfo(h, None))
            except OSError:
                pass

    # ------------------------------------------------------------- checks
    def _deny(self, what: str) -> NoReturn:
        raise PermissionError(f"{PREFIX}: {what} is not allowed for generated code")

    def writable(self, path: Any) -> bool:
        if isinstance(path, int):
            return True                   # an already open descriptor
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not isinstance(path, (str, os.PathLike)):
            return False
        if os.fspath(path) == os.devnull:
            return True
        real = os.path.realpath(os.fspath(path))
        return any(real == r or real.startswith(r.rstrip(os.sep) + os.sep) for r in self.roots)

    def check_write(self, path: Any, event: str, dir_fd: Any = None) -> None:
        if isinstance(dir_fd, int) and dir_fd >= 0 and not isinstance(path, int):   # -100 (AT_FDCWD) = none given
            base = fd_path(dir_fd)        # a path relative to an open directory: check where it really points
            if base is None:
                self._deny(f"{event} relative to a directory descriptor")
            path = os.path.join(base, os.fsdecode(path) if isinstance(path, bytes) else os.fspath(path))
        if not self.writable(path):
            self._deny(f"{event} {path!r} (outside {os.pathsep.join(self.roots)})")

    def host_ok(self, host: Any) -> bool:
        if host is None:
            return True
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        host = str(host).strip("[]").lower()
        if host in ("localhost", "localhost.localdomain", "") or host in self.hosts or host in self.ips:
            return True
        try:
            return ipaddress.ip_address(host.split("%")[0]).is_loopback
        except ValueError:
            return False

    def check_address(self, address: Any, event: str) -> None:
        if isinstance(address, tuple) and address:
            if not self.host_ok(address[0]):
                self._deny(f"{event} to {address[0]}")
        else:                              # AF_UNIX path or anything else
            self._deny(f"{event} to {address!r}")

    # --------------------------------------------------------------- hook
    def __call__(self, event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            path, mode, flags = [*args, None, None, 0][:3]
            writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool((flags or 0) & WRITE_FLAGS)
            if writes:
                self.check_write(path, "writing")
            elif mode is None and isinstance(path, (str, bytes, os.PathLike)) and os.path.isdir(path) \
                    and not self.writable(path):
                # os.open() of a directory gives a dir_fd, and the "open" audit event doesn't show dir_fd:
                # without this, open("x", dir_fd=...) could write anywhere
                self._deny(f"opening the directory {path!r} (outside {os.pathsep.join(self.roots)})")
        elif event in PATH_EVENTS:
            for i, fd in PATH_EVENTS[event]:
                if i < len(args):
                    self.check_write(args[i], event, args[fd] if fd is not None and fd < len(args) else None)
        elif event == "sqlite3.connect":
            db = args[0] if args else ":memory:"
            db = os.fsdecode(db) if isinstance(db, bytes) else str(db)
            if db not in ("", ":memory:") and not db.startswith("file::memory:"):
                if db.startswith("file:"):
                    db = db[5:].split("?", 1)[0]
                self.check_write(db, "opening the database")
        elif event in PROCESS_EVENTS:
            self._deny(f"starting a process ({event})")
        elif event in ESCAPE_EVENTS:
            self._deny(event)
        elif event == "socket.getaddrinfo":
            if args and not self.host_ok(args[0]):
                self._deny(f"looking up {args[0]}")
        elif event in ("socket.connect", "socket.connect_ex", "socket.sendto", "socket.sendmsg"):
            if len(args) > 1:
                self.check_address(args[1], event)
        elif event == "import" and args and args[0] in ("_ctypes", "ctypes", "_posixsubprocess", "_winapi") \
                and args[0] not in sys.modules:  # ImportError, so code that copes with a missing module still works
            raise ImportError(f"{PREFIX}: importing {args[0]} is not allowed for generated code", name=args[0])


def install(write_roots: list[str], hosts: list[str]) -> Guard:
    import subprocess                      # loaded (and its process entry point disarmed) before the hook exists

    guard = Guard(write_roots, hosts)

    def refused(*_a: Any, **_k: Any) -> Any:
        raise PermissionError(f"{PREFIX}: starting a process is not allowed for generated code")

    try:
        import _posixsubprocess            # the C entry point behind subprocess; not audited itself
        _posixsubprocess.fork_exec = refused
    except ImportError:                    # Windows: CreateProcess is audited
        pass
    if hasattr(subprocess, "_fork_exec"):
        subprocess._fork_exec = refused
    sys.addaudithook(guard)
    return guard


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    install(os.environ.get("SP2REACT_GUARD_WRITE", "").split(os.pathsep),
            os.environ.get("SP2REACT_GUARD_HOSTS", "").split(","))
    if argv[1] == "-m":
        sys.argv = [argv[2], *argv[3:]]
        sys.path[0] = os.getcwd()
        runpy.run_module(argv[2], run_name="__main__", alter_sys=True)
    elif argv[1] == "-c":
        sys.argv = ["-c", *argv[3:]]
        sys.path[0] = os.getcwd()
        exec(compile(argv[2], "<string>", "exec"), {"__name__": "__main__"})  # noqa: S102  the caller's own loader code
    else:
        sys.argv = argv[1:]
        runpy.run_path(argv[1], run_name="__main__")


if __name__ == "__main__":
    main(sys.argv)
