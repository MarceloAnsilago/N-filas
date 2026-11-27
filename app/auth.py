"""Login compartilhado por unidade e selecao do banco de atendimento."""
from contextlib import contextmanager
from pathlib import Path
import hmac
import secrets
import sqlite3
from threading import Lock

from flask import Blueprint, Response, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, painel_cores, painel_logo, painel_tempo, painel_youtube
from .painel_events import PainelEvents

bp = Blueprint("auth", __name__)


@contextmanager
def accounts():
    # O cadastro fica no banco original; bancos das unidades nunca decidem a identidade.
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def unit_path(unit):
    original = Path(current_app.config["DB_PATH"])
    return str(original if unit["legacy"] else original.parent / (original.stem + "_unidades") / f"{unit['id']}.db")


def select_unit(unit):
    g.unidade = dict(unit)
    g.db_path = unit_path(unit)
    with current_app.extensions["unidades_lock"]:
        g.painel_events = current_app.extensions["unidades_events"].setdefault(unit["id"], PainelEvents())


def init_auth(app):
    if not app.secret_key or app.secret_key in {"supersecret", "troque-esta-chave-por-uma-nova"}:
        secret_path = Path(app.config["DB_PATH"]).with_suffix(".session_secret")
        try:
            with secret_path.open("x", encoding="ascii") as secret_file:
                secret_file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.secret_key = secret_path.read_text(encoding="ascii").strip()
    schema = """
        CREATE TABLE IF NOT EXISTS unidade_login (
            id INTEGER PRIMARY KEY, nome TEXT NOT NULL, login TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL, legacy INTEGER NOT NULL DEFAULT 0,
            is_admin INTEGER NOT NULL DEFAULT 0)
    """
    with accounts() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(schema)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(unidade_login)")}
        if "is_admin" not in columns:
            conn.execute("ALTER TABLE unidade_login ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if "print_token" in columns:
            conn.execute("ALTER TABLE unidade_login RENAME TO unidade_login_anterior")
            conn.execute(schema)
            conn.execute("""
                INSERT INTO unidade_login (id, nome, login, senha_hash, legacy, is_admin)
                SELECT id, nome, login, senha_hash, legacy, is_admin FROM unidade_login_anterior
            """)
            conn.execute("DROP TABLE unidade_login_anterior")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS painel_cor (
                unidade_id INTEGER NOT NULL, item TEXT NOT NULL, cor TEXT NOT NULL,
                PRIMARY KEY (unidade_id, item)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS painel_logo (
                unidade_id INTEGER PRIMARY KEY, imagem BLOB NOT NULL
            )
        """)
        colunas_logo = {row["name"] for row in conn.execute("PRAGMA table_info(painel_logo)")}
        for coluna, padrao in (("largura", 100), ("altura", 100), ("esticar", 0)):
            if coluna not in colunas_logo:
                conn.execute(f"ALTER TABLE painel_logo ADD COLUMN {coluna} INTEGER NOT NULL DEFAULT {padrao}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS painel_youtube (
                unidade_id INTEGER PRIMARY KEY, link TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS painel_tempo (
                unidade_id INTEGER PRIMARY KEY, municipio TEXT NOT NULL
            )
        """)
    app.extensions["unidades_lock"] = Lock()
    app.extensions["unidades_events"] = {}
    app.register_blueprint(bp)
    app.before_request(require_unit)
    app.after_request(private_response)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def private_response(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


def require_unit():
    if request.endpoint in {"auth.login", "auth.admin_login", "static"} or request.endpoint is None:
        return None
    with accounts() as conn:
        unit = conn.execute("SELECT * FROM unidade_login WHERE id = ?", (session.get("unidade_id"),)).fetchone()
    if unit is None:
        session.clear()
        if request.path.endswith(("/status", "/events")) or request.method != "GET":
            return jsonify(ok=False, message="Entre com o login da unidade."), 401
        return redirect(url_for("auth.admin_login") if request.endpoint == "web.admin" else url_for("auth.login", next=request.full_path))
    select_unit(unit)
    if request.endpoint == "web.admin" and not unit["is_admin"]:
        return redirect(url_for("auth.admin_login"))
    if unit["is_admin"] and request.endpoint not in {"web.admin", "auth.logo_painel", "auth.logout"}:
        if request.path.endswith(("/status", "/events")) or request.method != "GET":
            return jsonify(ok=False, message="Entre com o login da unidade."), 401
        return redirect(url_for("auth.login", next=request.path))


def form_token():
    if "form_token" not in session:
        session["form_token"] = secrets.token_urlsafe(32)
    return session["form_token"]


def valid_form():
    return hmac.compare_digest(session.get("form_token", ""), request.form.get("form_token", "!"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    return login_page(admin_only=False)


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return login_page(admin_only=True)


def login_page(admin_only):
    if request.method == "POST":
        if not valid_form():
            flash("Atualize a pagina e tente novamente.", "warning")
        else:
            username = (request.form.get("login") or "").strip().lower()
            with accounts() as conn:
                unit = conn.execute("SELECT * FROM unidade_login WHERE login = ?", (username,)).fetchone()
            if unit and bool(unit["is_admin"]) == admin_only and check_password_hash(unit["senha_hash"], request.form.get("senha") or ""):
                session.clear()
                session["unidade_id"] = unit["id"]
                session.permanent = True
                target = request.args.get("next", "")
                # Somente rotas locais conhecidas podem ser destino do login.
                if admin_only:
                    return redirect(url_for("web.admin"))
                allowed = {"/", "/chamar", "/painel", "/painel/compacto", "/gerar", "/senhas", "/historico"}
                return redirect(target if target.split("?", 1)[0] in allowed else url_for("web.admin" if unit["is_admin"] else "web.chamar"))
            flash("Login ou senha incorretos.", "warning")
    unidades = []
    if not admin_only:
        with accounts() as conn:
            unidades = [dict(row) for row in conn.execute(
                "SELECT nome, login FROM unidade_login WHERE is_admin = 0 ORDER BY nome COLLATE NOCASE"
            )]
    return render_template("login.html", admin_only=admin_only, unidades=unidades, form_token=form_token())


def admin_page():
    unidade_painel = request.args.get("unidade_painel", type=int)
    aba = request.args.get("aba")
    if aba not in {"logo", "link", "tempo", "senhas"}:
        aba = None
    with accounts() as conn:
        if "unidade_painel" in request.args:
            unidade = conn.execute(
                "SELECT id FROM unidade_login WHERE id = ? AND is_admin = 0", (unidade_painel,)
            ).fetchone()
            if unidade is None:
                abort(404)
        if request.method == "POST" and unidade_painel is not None:
            destino = url_for("web.admin", unidade_painel=unidade_painel, aba=aba, _anchor=f"unidade-{unidade_painel}")
            if aba == "logo":
                request.max_content_length = painel_logo.MAX_ARQUIVO + 64 * 1024
            try:
                acao = request.form.get("acao")
            except RequestEntityTooLarge:
                if aba != "logo":
                    raise
                flash("A imagem deve ter no máximo 5 MB.", "warning")
                return redirect(destino)
            if not valid_form():
                flash("Atualize a página e tente novamente.", "warning")
            elif aba != "senhas" and acao in {"salvar_cores", "restaurar_cores"}:
                cores = {} if acao == "restaurar_cores" else painel_cores.validar_cores(request.form)
                if cores is None:
                    flash("Informe uma cor válida para cada item.", "warning")
                else:
                    painel_cores.gravar_cores(conn, unidade_painel, cores)
                    flash("Cores do painel atualizadas.", "success")
            elif aba == "logo" and acao == "salvar_logo":
                try:
                    ajuste = painel_logo.ler_ajuste(request.form)
                    arquivo = request.files.get("logo")
                    if arquivo:
                        imagem = painel_logo.preparar_logo(arquivo)
                        conn.execute(
                            "INSERT OR REPLACE INTO painel_logo (unidade_id, imagem, largura, altura, esticar) VALUES (?, ?, ?, ?, ?)",
                            (unidade_painel, imagem, *ajuste),
                        )
                    else:
                        atualizado = conn.execute(
                            "UPDATE painel_logo SET largura = ?, altura = ?, esticar = ? WHERE unidade_id = ?",
                            (*ajuste, unidade_painel),
                        )
                        if not atualizado.rowcount:
                            raise ValueError("Escolha uma imagem PNG, JPEG ou WebP.")
                except ValueError as erro:
                    flash(str(erro), "warning")
                else:
                    flash("Logo do painel atualizado.", "success")
            elif aba == "logo" and acao == "remover_logo":
                conn.execute("DELETE FROM painel_logo WHERE unidade_id = ?", (unidade_painel,))
                flash("Logo padrão restaurado.", "success")
            elif aba == "tempo" and acao == "salvar_tempo":
                estado = painel_tempo.ESTADOS.get(request.form.get("uf"))
                municipio = request.form.get("municipio")
                if not estado or municipio not in estado["municipios"]:
                    flash("Escolha um município do estado selecionado.", "warning")
                else:
                    conn.execute(
                        "INSERT OR REPLACE INTO painel_tempo (unidade_id, municipio) VALUES (?, ?)",
                        (unidade_painel, municipio),
                    )
                    flash("Local da previsão do tempo salvo.", "success")
            elif aba == "link" and acao == "salvar_link":
                link = request.form.get("link_youtube", "").strip()
                if not link:
                    conn.execute("DELETE FROM painel_youtube WHERE unidade_id = ?", (unidade_painel,))
                    flash("Mídia padrão do painel restaurada.", "success")
                elif len(link) > 2048 or not painel_youtube.origem_embed(link, muted=True):
                    flash("Informe um link válido de vídeo ou playlist do YouTube.", "warning")
                else:
                    conn.execute(
                        "INSERT OR REPLACE INTO painel_youtube (unidade_id, link) VALUES (?, ?)",
                        (unidade_painel, link),
                    )
                    flash("Link do painel salvo.", "success")
            else:
                abort(400)
            return redirect(destino)

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        username = nome.lower()
        password = request.form.get("senha") or ""
        if not valid_form():
            flash("Atualize a pagina e tente novamente.", "warning")
        elif not 3 <= len(nome) <= 100 or not password:
            flash("Informe um nome de unidade de 3 a 100 caracteres e uma senha.", "warning")
        else:
            try:
                with accounts() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    first = conn.execute("SELECT 1 FROM unidade_login WHERE is_admin = 0 LIMIT 1").fetchone() is None
                    cursor = conn.execute(
                        "INSERT INTO unidade_login (nome, login, senha_hash, legacy) VALUES (?, ?, ?, ?)",
                        (nome, username, generate_password_hash(password), int(first)),
                    )
                    unit = conn.execute("SELECT * FROM unidade_login WHERE id = ?", (cursor.lastrowid,)).fetchone()
                administrator = dict(g.unidade)
                try:
                    select_unit(unit)
                    db.init_db()
                    db.salvar_unidade_padrao(nome)
                finally:
                    select_unit(administrator)
                flash("Unidade cadastrada com sucesso.", "success")
                return redirect(url_for("web.admin"))
            except sqlite3.IntegrityError:
                flash("Este login ja esta em uso. Escolha outro.", "warning")
    with accounts() as conn:
        unidades = [dict(row) for row in conn.execute("SELECT id, nome, login FROM unidade_login WHERE is_admin = 0 ORDER BY nome")]
        cores = painel_cores.ler_cores(conn, unidade_painel) if unidade_painel is not None else {}
    return render_template("admin.html", unidades=unidades, unidade_painel=unidade_painel, aba=aba,
                           itens_painel=painel_cores.ITENS, cores=cores, form_token=form_token(),
                           logo=obter_logo_painel(unidade_painel) if aba == "logo" else None,
                           link_youtube=obter_link_painel(unidade_painel) if aba == "link" else "",
                           local_tempo=obter_local_tempo(unidade_painel) if aba == "tempo" else None,
                           estados=painel_tempo.ESTADOS)


def obter_local_tempo(unidade_id):
    if unidade_id is None:
        return painel_tempo.local_municipio()
    with accounts() as conn:
        return painel_tempo.ler_local(conn, unidade_id)


def obter_link_painel(unidade_id):
    with accounts() as conn:
        row = conn.execute(
            "SELECT link FROM painel_youtube WHERE unidade_id = ?", (unidade_id,)
        ).fetchone()
    return row["link"] if row else ""


def obter_logo_painel(unidade_id):
    if unidade_id is not None:
        with accounts() as conn:
            logo = conn.execute(
                "SELECT largura, altura, esticar FROM painel_logo WHERE unidade_id = ?", (unidade_id,)
            ).fetchone()
        if logo:
            return dict(logo, url=url_for("auth.logo_painel", unidade_id=unidade_id))


@bp.get("/painel/logo/<int:unidade_id>")
def logo_painel(unidade_id):
    if not g.unidade["is_admin"] and g.unidade["id"] != unidade_id:
        abort(404)
    with accounts() as conn:
        logo = conn.execute("SELECT imagem FROM painel_logo WHERE unidade_id = ?", (unidade_id,)).fetchone()
    if logo is None:
        abort(404)
    return Response(logo["imagem"], mimetype="image/png", headers={"X-Content-Type-Options": "nosniff"})


def cores_painel_da_unidade():
    unidade = g.get("unidade")
    if unidade is None:
        return {}
    with accounts() as conn:
        return painel_cores.ler_cores(conn, unidade["id"])


@bp.post("/logout")
def logout():
    if not valid_form():
        return "Formulario expirado. Atualize a pagina.", 400
    admin_only = bool(g.unidade["is_admin"])
    session.clear()
    return redirect(url_for("auth.admin_login" if admin_only else "auth.login"))


@bp.app_context_processor
def auth_context():
    return {"unidade_conectada": getattr(g, "unidade", None), "auth_form_token": form_token}
