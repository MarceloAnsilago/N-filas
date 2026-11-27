"""Publica a revisão aprovada do Nfilas com o usuário nfilas."""

import argparse
import fcntl
import http.client
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE = Path("/opt/nfilas")
APP = BASE / "app"
VENV = BASE / ".venv"
DATA = BASE / "data"
STATE = BASE / ".deploy"
REMOTE = "https://github.com/MarceloAnsilago/N-filas.git"
REPOSITORY = "MarceloAnsilago/N-filas"
SERVICE = "nfilas.service"
SHA = re.compile(r"[0-9a-f]{40}")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def state_read(name):
    path = STATE / name
    return path.read_text().strip() if path.exists() else ""


def state_write(name, value):
    path = STATE / name
    temp = path.with_suffix(".tmp")
    temp.write_text(value + "\n")
    temp.replace(path)


def service(action):
    run("/usr/bin/sudo", "-n", "/usr/bin/systemctl", action, SERVICE)


def healthy():
    for _ in range(30):
        with closing(http.client.HTTPConnection("127.0.0.1", 8081, timeout=2)) as conn:
            try:
                conn.request("GET", "/login")
                with conn.getresponse() as response:
                    if response.status == 200 and subprocess.run(
                        ["/usr/bin/systemctl", "is-active", "--quiet", SERVICE]
                    ).returncode == 0:
                        return
            except (OSError, http.client.HTTPException):
                pass
        time.sleep(1)
    raise RuntimeError("nfilas.service não respondeu HTTP 200 em /login")


def main_sha():
    result = run("git", "ls-remote", "--exit-code", REMOTE, "refs/heads/main",
                 capture_output=True, text=True, timeout=30)
    sha, ref = result.stdout.split()
    if ref != "refs/heads/main" or not SHA.fullmatch(sha):
        raise RuntimeError("Referência main inválida")
    return sha


def approved_run(sha):
    query = urlencode({"branch": "main", "event": "push", "head_sha": sha, "per_page": 1})
    url = f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/ci.yml/runs?{query}"
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                  "User-Agent": "nfilas-oracle-deploy"})
    with urlopen(request, timeout=20) as response:
        runs = json.load(response)["workflow_runs"]
    if not runs:
        return None
    ci = runs[0]
    if (ci["head_sha"] == sha and ci["head_branch"] == "main" and ci["event"] == "push"
            and ci["path"] in {".github/workflows/ci.yml", ".github/workflows/ci.yml@main",
                               ".github/workflows/ci.yml@refs/heads/main"}
            and ci["head_repository"]["full_name"].casefold() == REPOSITORY.casefold()
            and ci["status"] == "completed" and ci["conclusion"] == "success"):
        return f'{ci["id"]}.{ci["run_attempt"]}'
    return None


def databases(directory):
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("O diretório de dados deve conter somente caminhos locais")
        if path.is_file() and not path.name.endswith(".nfilas-restore"):
            with path.open("rb") as stream:
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"} or (
                    stream.read(16) == b"SQLite format 3\x00"
                ):
                    yield path.relative_to(directory)


def snapshot(destination):
    destination.mkdir()
    for relative in sorted(databases(DATA)):
        source = DATA / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(target)) as backup:
                original.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("Falha na verificação de integridade do backup SQLite")
        shutil.copymode(source, target)


def restore_databases(source):
    backups = set(databases(source))
    for relative in sorted(backups | set(databases(DATA))):
        target = DATA / relative
        for suffix in ("-wal", "-shm", "-journal"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)
        if relative in backups:
            temp = target.with_name(target.name + ".nfilas-restore")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, temp)
            temp.replace(target)
        else:
            target.unlink(missing_ok=True)


def restore(directory):
    if (directory / "snapshot-ready").exists():
        service("stop")
        for live, previous in ((APP, directory / "previous-app"),
                               (VENV, directory / "previous-venv")):
            if os.path.lexists(previous):
                if os.path.lexists(live):
                    live.rename(directory / ("replaced-" + live.name))
                previous.rename(live)
        restore_databases(directory / "sqlite")
    service("start")
    healthy()


def recover():
    pending = state_read("pending")
    if not pending:
        return
    action, name = pending.split()
    directory = STATE / name
    if action == "rollback" or name != state_read("active"):
        print(f"Restaurando a versão anterior à publicação {name}.", flush=True)
        restore(directory)
        if action == "rollback":
            state_write("active", (directory / "previous-active").read_text().strip())
        (STATE / ("rejected-" + name.rsplit("-", 1)[0])).touch()
    (STATE / "pending").unlink()


def stage(directory, sha):
    repo = directory / "git"
    archive = directory / "app.tar"
    candidate = directory / "candidate"
    run("git", "init", "--bare", "--quiet", repo)
    run("git", "-C", repo, "fetch", "--quiet", "--depth=1", REMOTE, "refs/heads/main",
        timeout=180)
    fetched = run("git", "-C", repo, "rev-parse", "FETCH_HEAD",
                  capture_output=True, text=True).stdout.strip()
    if fetched != sha:
        return False
    run("git", "-C", repo, "archive", "--format=tar", "-o", archive, sha, "--", ".",
        ":(exclude)artifacts", ":(exclude)ultima_senha.db.b64", timeout=90)
    with tarfile.open(archive) as tar:
        tar.extractall(candidate, filter="data")
    archive.unlink()
    shutil.rmtree(repo)
    if os.path.lexists(candidate / ".env"):
        raise RuntimeError("O commit contém um .env na raiz")
    shutil.copyfile(APP / ".env", candidate / ".env")
    (candidate / ".env").chmod(0o600)
    venv = directory / "venv"
    run(sys.executable, "-m", "venv", venv, timeout=120)
    python = venv / "bin/python"
    run(python, "-m", "pip", "install", "-r", "requirements.deploy.txt",
        cwd=candidate, timeout=300)
    run(python, "-m", "pip", "check", cwd=candidate, timeout=60)
    run(python, "-I", "-c", """
from pathlib import Path
from dotenv import dotenv_values

db = Path(dotenv_values(".env").get("PAINEL_DB_PATH") or "")
data = Path("/opt/nfilas/data")
if not (db.is_absolute() and db.resolve().is_relative_to(data) and db.is_file()):
    raise SystemExit("PAINEL_DB_PATH deve apontar para um banco existente em /opt/nfilas/data.")
""", cwd=candidate, timeout=15)
    return True


def deploy():
    sha = main_sha()
    active = state_read("active")
    if active.startswith(sha + "-"):
        return
    ci = approved_run(sha)
    if ci is None:
        print(f"Aguardando aprovação no CI de {sha}.")
        return
    approval = f"{sha}-{ci}"
    if (STATE / ("rejected-" + approval)).exists():
        print(f"Publicação {approval} bloqueada após rollback.")
        return
    if not APP.is_dir() or not VENV.is_dir() or not (APP / ".env").is_file():
        raise RuntimeError("Aplicação, ambiente virtual ou .env ausente")
    directory = Path(tempfile.mkdtemp(prefix=approval + "-", dir=STATE))
    try:
        if not stage(directory, sha) or main_sha() != sha or approved_run(sha) != ci:
            print("A main ou a aprovação mudou durante a preparação.")
            shutil.rmtree(directory)
            return
    except Exception:
        shutil.rmtree(directory)
        raise
    name = directory.name
    (directory / "previous-active").write_text(active + "\n")
    state_write("pending", f"deploy {name}")
    try:
        service("stop")
        snapshot(directory / "sqlite")
        (directory / "snapshot-ready").touch()
        APP.rename(directory / "previous-app")
        (directory / "candidate").rename(APP)
        VENV.rename(directory / "previous-venv")
        VENV.symlink_to(directory / "venv", target_is_directory=True)
        service("start")
        healthy()
        state_write("active", name)
    except BaseException:
        recover()
        raise
    (STATE / "pending").unlink()
    print(f"Publicado {sha} com aprovação do CI {ci}.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("deploy", "rollback"), default="deploy", nargs="?")
    args = parser.parse_args()
    if pwd.getpwuid(os.geteuid()).pw_name != "nfilas":
        sys.exit("Execute com o usuário nfilas.")
    os.umask(0o077)
    if not DATA.is_dir() or DATA.is_symlink():
        sys.exit("O diretório local /opt/nfilas/data é obrigatório.")
    STATE.mkdir(exist_ok=True)
    with (STATE / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Já existe uma operação de publicação em andamento.")
            return 1 if args.command == "rollback" else 0
        pending = state_read("pending")
        recover()
        if args.command == "rollback":
            if pending:
                print("Operação pendente recuperada. Confira a versão ativa antes de outro rollback.")
                return 0
            active = state_read("active")
            if not active:
                sys.exit("Nenhuma publicação automatizada para reverter.")
            state_write("pending", f"rollback {active}")
            recover()
        else:
            deploy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
