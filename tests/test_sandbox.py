"""Generated code (agent-written handlers) runs in the sandbox: what it may and may not do.

The guard tests run real escape attempts in a child process under sandbox_guard.py. The container tests check
the command sp2react gives Docker/Podman; the container itself runs in CI (tests.yml, sandbox-container job).
"""
from __future__ import annotations

import json
import socket
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from sp2react import sandbox
from sp2react.sandbox import Sandbox


def run_guarded(tmp_path: Path, code: str, hosts: list[str] | None = None) -> sandbox.Result:
    box = Sandbox("guard", hosts=hosts or [])
    (tmp_path / "app").mkdir(exist_ok=True)
    return box.python(["-c", textwrap.dedent(code)], tmp_path / "app", {}, write=[tmp_path / "app"], read=[], timeout=60)


def blocked(r: sandbox.Result) -> bool:
    return r.code != 0 and "sp2react sandbox" in r.output


def test_ordinary_work_inside_the_app_folder_is_allowed(tmp_path):
    r = run_guarded(tmp_path, """
        import json, os, sqlite3, tempfile, pathlib, uuid, hashlib, datetime, decimal
        pathlib.Path("data").mkdir(exist_ok=True)
        pathlib.Path("data/x.json").write_text(json.dumps({"ok": 1}))
        db = sqlite3.connect("data/test.db"); db.execute("create table t (a)"); db.commit(); db.close()
        sqlite3.connect(":memory:").close()
        with tempfile.NamedTemporaryFile() as f: f.write(b"x")
        os.remove("data/x.json")
        print(open("/dev/null", "w") and "ok")
    """)
    assert r.code == 0, r.output
    assert (tmp_path / "app" / "data" / "test.db").exists()


@pytest.mark.parametrize("code", [
    "open({outside!r}, 'w').write('x')",
    "import os; os.remove({victim!r})",
    "import os; os.rename({victim!r}, 'stolen')",
    "import shutil; shutil.rmtree({outside_dir!r})",
    "import os; fd = os.open({outside!r}, os.O_WRONLY | os.O_CREAT); os.write(fd, b'x')",
    "import sqlite3; sqlite3.connect({outside!r})",
    "import pathlib; pathlib.Path({outside!r}).write_text('x')",
    "import os; os.symlink('/', 'root-link'); open('root-link' + {outside!r}, 'w')",
    "import os; d = os.open({outside_dir!r}, os.O_RDONLY); os.open('new.txt', os.O_WRONLY | os.O_CREAT, dir_fd=d)",
    "import os; os.remove('keep.txt', dir_fd=os.open({outside_dir!r}, os.O_RDONLY))",
    "import os, pathlib; pathlib.Path('ok').mkdir(); d = os.open('ok', os.O_RDONLY); os.rename('../../outside/keep.txt', 'x', src_dir_fd=d)",
])
def test_writes_outside_the_app_folder_are_refused(tmp_path, code):
    (tmp_path / "outside").mkdir()
    victim = tmp_path / "outside" / "keep.txt"
    victim.write_text("keep")
    r = run_guarded(tmp_path, code.format(outside=str(tmp_path / "outside" / "new.txt"), victim=str(victim),
                                          outside_dir=str(tmp_path / "outside")))
    assert blocked(r), r.output
    assert victim.read_text() == "keep" and not (tmp_path / "outside" / "new.txt").exists()


@pytest.mark.parametrize("code", [
    "import subprocess; subprocess.run(['echo', 'hi'])",
    "import os; os.system('echo hi')",
    "import os; os.execv('/bin/echo', ['echo'])",
    "import os; os.fork()",
    "import os; os.posix_spawn('/bin/echo', ['echo'], {})",
    "import subprocess, sys; (getattr(subprocess, '_fork_exec', None) or sys.modules['_posixsubprocess'].fork_exec)(['/bin/echo'])",
    "import sys; sys.modules['_posixsubprocess'].fork_exec(['/bin/echo'])",
    "import multiprocessing as m; p = m.Process(target=print); p.start(); p.join()",
])
def test_starting_processes_is_refused(tmp_path, code):
    if sys.platform == "win32" and ("fork" in code or "posix_spawn" in code or "execv" in code):
        pytest.skip("POSIX only")
    r = run_guarded(tmp_path, code)
    assert blocked(r), r.output


@pytest.mark.parametrize("code", [
    "import ctypes; ctypes.CDLL(None)",
    "import gc; gc.get_objects()",
    "import gc; gc.get_referrers(object())",
])
def test_ways_around_the_guard_are_refused(tmp_path, code):
    r = run_guarded(tmp_path, code)
    assert r.code != 0 and "sp2react sandbox" in r.output, r.output


@pytest.fixture
def listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    threading.Thread(target=lambda: [srv.accept()[0].close() for _ in range(5)], daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()


def test_network_only_to_loopback_and_the_database_host(tmp_path, listener):
    ok = run_guarded(tmp_path, f"import socket; socket.create_connection(('127.0.0.1', {listener}), 5).close()")
    assert ok.code == 0, ok.output
    out = run_guarded(tmp_path, "import socket; socket.create_connection(('192.0.2.10', 443), 2)")
    assert blocked(out), out.output
    dns = run_guarded(tmp_path, "import socket; socket.getaddrinfo('example.com', 443)")
    assert blocked(dns), dns.output
    url = run_guarded(tmp_path, "import urllib.request; urllib.request.urlopen('http://203.0.113.5/', timeout=2)")
    assert "sp2react sandbox" in url.output, url.output
    db = run_guarded(tmp_path, "import socket; socket.getaddrinfo('db.example.test', 3306)", hosts=["db.example.test"])
    assert "sp2react sandbox" not in db.output, db.output     # allowed (it may still fail to resolve)


def test_descriptor_relative_writes_inside_the_folder_still_work(tmp_path):
    r = run_guarded(tmp_path, """
        import os, pathlib
        pathlib.Path("sub").mkdir()
        d = os.open("sub", os.O_RDONLY)
        os.close(os.open("f.txt", os.O_WRONLY | os.O_CREAT, dir_fd=d))
        os.mkdir("inner", dir_fd=d)
        os.rmdir("inner", dir_fd=d)
        import shutil; shutil.rmtree("sub")
    """)
    assert r.code == 0, r.output


def test_ntlm_never_answers_over_plain_http():
    from sp2react import transport

    class Fake:
        url = "http://sp.example.com/x"
    auth = transport.NtlmAuth("CORP\\svc", "pw")
    with pytest.raises(transport.RequestException, match="plain HTTP"):
        auth.handle_401(None, Fake(), None)       # e.g. after an https -> http redirect


def test_the_guard_cannot_be_removed(tmp_path):
    r = run_guarded(tmp_path, """
        import sys
        sys.addaudithook(lambda *a: None)           # adding hooks never removes the guard
        open('/etc/sp2react-test', 'w')
    """)
    assert blocked(r), r.output


def test_off_mode_runs_plain_processes(tmp_path):
    (tmp_path / "app").mkdir()
    r = Sandbox("off").python(["-c", "import subprocess, sys; subprocess.run([sys.executable, '-c', 'print(1)'])"],
                              tmp_path / "app", {}, write=[tmp_path / "app"], read=[], timeout=60)
    assert r.code == 0, r.output


def test_auto_falls_back_to_the_guard_without_a_container_runtime(monkeypatch):
    monkeypatch.setattr(sandbox, "container_runtime", lambda: None)
    box = Sandbox("auto")
    assert box.resolve() == "guard" and "no Docker or Podman" in box.describe()
    monkeypatch.setattr(sandbox, "container_runtime", lambda: None)
    with pytest.raises(RuntimeError, match="neither Podman nor Docker"):
        Sandbox("container").resolve()


def test_the_container_gets_no_network_no_host_files_and_no_secrets(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake(cmd, cwd, timeout, env, on_timeout=None):
        calls.append(cmd)
        return sandbox.Result(1 if cmd[1:3] == ["image", "inspect"] else 0, json.dumps({}), "")   # no image yet

    monkeypatch.setattr(sandbox, "container_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(sandbox, "run_process", fake)
    monkeypatch.setenv("SP_PASSWORD", "hunter2")
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True)
    (app / "backend" / "requirements.txt").write_text("fastapi\n")
    box = Sandbox("container")
    box.python(["-m", "pytest", "tests"], app / "backend", {"DB_PATH": str(app / "backend" / "data" / "t.db")},
               write=[app / "backend"], read=[app])
    run = next(c for c in calls if c[1] == "run")
    s = " ".join(run)
    assert "--network none" in s and "--read-only" in s and "--cap-drop ALL" in s and "no-new-privileges" in s
    assert f"{app.resolve()}:/work/app:ro" in s and f"{(app / 'backend').resolve()}:/work/app/backend:rw" in s
    assert s.index("/work/app:ro") < s.index("/work/app/backend:rw")          # nested writable mount comes second
    assert "DB_PATH=/work/app/backend/data/t.db" in s and "-w /work/app/backend" in s
    assert "hunter2" not in s and "SP_PASSWORD" not in s
    assert run[-5:] == ["python", "/sp2react/guard.py", "-m", "pytest", "tests"]
    assert any(c[1] == "build" for c in calls)                # image built from container/Dockerfile

    calls.clear()
    Sandbox("container", image="registry.example/checks:1", hosts=["db.example"]).python(
        ["-m", "pytest"], app / "backend", {"DB_URL": "mysql+pymysql://u:p@db.example/sea"}, write=[app / "backend"], read=[app])
    run = calls[-1]
    s = " ".join(run)
    assert "--network host" in s and "SP2REACT_GUARD_HOSTS=db.example" in s and "registry.example/checks:1" in run
    assert not any(c[1] == "build" for c in calls)

    calls.clear()
    (tmp_path / "db").mkdir()
    Sandbox("container", image="img", data=[tmp_path / "db"]).python(
        ["-m", "pytest"], app / "backend", {"DB_URL": f"sqlite:///{tmp_path / 'db' / 'sea.db'}"}, write=[app / "backend"], read=[app])
    s = " ".join(calls[-1])
    assert "DB_URL=sqlite:////work/w1/sea.db" in s and f"{(tmp_path / 'db').resolve()}:/work/w1:rw" in s


def test_a_malicious_handler_cannot_escape_the_backend_tests(tmp_path):
    """End to end: a custom handler that tries to read secrets, write outside and call home runs under the guard."""
    from sp2react.checks import backend_tests

    out = tmp_path / "app"
    (out / "backend" / "app").mkdir(parents=True)
    (out / "backend" / "tests").mkdir()
    (tmp_path / "home").mkdir()
    (out / "backend" / "app" / "__init__.py").write_text("")
    (out / "backend" / "app" / "handler.py").write_text(textwrap.dedent(f"""
        import os, subprocess
        LEAK = {{k: v for k, v in os.environ.items() if "PASSWORD" in k}}
        def attack():
            open({str(tmp_path / "home" / "pwned")!r}, "w").write("x")
        def shell():
            subprocess.run(["id"])
    """))
    (out / "backend" / "tests" / "test_h.py").write_text(textwrap.dedent("""
        import pytest
        from app import handler
        def test_no_secrets(): assert handler.LEAK == {}
        def test_write():
            with pytest.raises(PermissionError): handler.attack()
        def test_shell():
            with pytest.raises(PermissionError): handler.shell()
    """))
    import os
    os.environ["SP_PASSWORD_FOR_TEST"] = "hunter2"
    try:
        sandbox.HIDDEN_ENV.add("SP_PASSWORD_FOR_TEST")
        check = backend_tests(out, sandbox=Sandbox("guard"))
    finally:
        sandbox.HIDDEN_ENV.discard("SP_PASSWORD_FOR_TEST")
        del os.environ["SP_PASSWORD_FOR_TEST"]
    assert check.ok, check.output
    assert "sandbox: guard" in check.name and not (tmp_path / "home" / "pwned").exists()


# ---------------------------------------------------------------------------------------------------- container
CONTAINER = pytest.mark.skipif(not __import__("os").environ.get("SP2REACT_TEST_CONTAINER"),
                               reason="needs Docker or Podman and network for the image (CI: tests.yml sandbox-container)")


@CONTAINER
def test_a_malicious_handler_cannot_escape_the_container(tmp_path):
    from sp2react.checks import backend_tests

    out = tmp_path / "app"
    (out / "backend" / "app").mkdir(parents=True)
    (out / "backend" / "tests").mkdir()
    (out / "backend" / "requirements.txt").write_text("")
    (out / "backend" / "app" / "__init__.py").write_text("")
    (out / "backend" / "tests" / "test_h.py").write_text(textwrap.dedent("""
        import os, socket, pytest
        def test_host_files_are_not_visible(): assert not os.path.exists("/home/runner") and not os.path.exists("/root/.ssh")
        def test_no_network():
            with pytest.raises(OSError): socket.create_connection(("1.1.1.1", 443), 3)
        def test_read_only_outside_backend():
            with pytest.raises(OSError): open("/usr/local/evil", "w")
        def test_backend_is_writable():
            st = os.stat(".")
            assert os.access(".", os.W_OK), (os.getuid(), os.getgid(), st.st_uid, st.st_gid, oct(st.st_mode))
            open("data.txt", "w").write("ok")
        def test_secrets_not_passed(): assert not [k for k in os.environ if "PASSWORD" in k]
    """))
    import os
    os.environ["SP_PASSWORD_FOR_TEST"] = "hunter2"
    try:
        check = backend_tests(out, sandbox=Sandbox("container"))
    finally:
        del os.environ["SP_PASSWORD_FOR_TEST"]
    assert check.ok, check.output
    assert "sandbox: container" in check.name and (out / "backend" / "data.txt").read_text() == "ok"


@CONTAINER
def test_the_pipeline_runs_generated_tests_in_a_container(tmp_path, monkeypatch):
    from conftest import make
    from mock_sharepoint import MockSharePoint
    from scripted_agents import scripted
    from sp2react.pipeline import Pipeline

    monkeypatch.setenv("SP_COOKIE", "FedAuth=test-cookie")
    with MockSharePoint() as m:
        p = Pipeline(make(tmp_path, m.site_url, auto_approve=True, run_builds=False, sandbox="container"),
                     llm=scripted(), progress=lambda s: None)
        p.run()
    report = (tmp_path / "ws" / "tests" / "iteration-0.md").read_text()
    assert "sandbox: container" in report and p.status("Dashboard", "test") == "done", report[-3000:]
