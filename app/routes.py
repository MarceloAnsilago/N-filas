from datetime import date, datetime
from collections import Counter
import logging
import os
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for, session, jsonify, Response, current_app, g

from . import db, painel_youtube
from .auth import cores_painel_da_unidade, obter_link_painel, obter_logo_painel

logger = logging.getLogger(__name__)


def _read_env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return fallback
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Invalid value %r for %s; using fallback %s", raw, name, fallback)
        return fallback


DEFAULT_UNIDADE = "ULSAV SMG"
DEFAULT_USUARIO = "admin"
DEFAULT_PLAYLIST_ID = "PLCUb0x5mK4DM"
FIELD_LABELS = {
    "senha_inicial": "senha inicial",
    "senha_final": "senha final",
}
MAX_PAINEL_ULTIMAS = _read_env_int("PAINEL_MAX_ULTIMAS", 8)
PRIORIDADE_LABELS = {
    "normal": "Senha normal",
    "preferencial": "Senha preferencial",
}

bp = Blueprint("web", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/admin", methods=["GET", "POST"])
def admin():
    from .auth import admin_page
    return admin_page()


@bp.route("/chamar", methods=["GET", "POST"])
def chamar():
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        terminal = (request.form.get("terminal") or "").strip()
        session["usuario_chamar"] = usuario
        session["terminal_chamar"] = terminal
    else:
        usuario = (request.args.get("usuario") or "").strip() or session.get("usuario_chamar", "")
        terminal = (request.args.get("terminal") or "").strip() or session.get("terminal_chamar", "")

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "chamar":
            if not terminal.isdigit():
                flash("O campo Terminal deve conter apenas numeros.", "warning")
                return redirect(url_for("web.chamar"))

            chamada_aberta = db.obter_chamada_aberta()
            if chamada_aberta:
                flash(
                    f"Aguarde o usuario {chamada_aberta.get('usuario', 'N/A')} finalizar no terminal {chamada_aberta.get('terminal', 'N/A')}.",
                    "warning",
                )
                return redirect(url_for("web.chamar"))

            proxima = db.proxima_senha_aguardando()
            if not proxima:
                flash("Nenhuma senha aguardando para chamada.", "info")
                return redirect(url_for("web.chamar"))

            hora_atual = datetime.now(db.FUSO_HORARIO).isoformat()
            db.atualizar_senha(
                proxima["id"],
                {
                    "hora": hora_atual,
                    "resposta": "chamando 1",
                    "status": "aberto",
                    "usuario": usuario or DEFAULT_USUARIO,
                    "terminal": int(terminal),
                },
            )
            _notify_painel()
            flash(f"Senha {int(proxima['senha']):03} chamada no terminal {terminal}.", "success")
            return redirect(url_for("web.chamar"))

        chamada_atual = db.obter_chamada_aberta()
        if not chamada_atual:
            flash("Nenhuma senha esta em atendimento no momento.", "info")
            return redirect(url_for("web.chamar"))

        if acao == "cancelar_chamada":
            db.atualizar_senha(
                chamada_atual["id"],
                {"status": "aguardando", "resposta": "", "usuario": "", "terminal": 0},
            )
            _notify_painel()
            flash(f"Chamada cancelada. Senha {int(chamada_atual['senha']):03} devolvida à fila.", "success")
        elif acao == "chamar_novamente":
            atual = (chamada_atual.get("resposta") or "chamando 1").split()
            try:
                numero_atual = int(atual[-1])
            except (ValueError, IndexError):
                numero_atual = 1
            novo_valor = f"chamando {numero_atual + 1}"
            db.atualizar_senha(chamada_atual["id"], {"resposta": novo_valor, "hora": datetime.now(db.FUSO_HORARIO).isoformat()})
            _notify_painel()
            flash("Senha chamada novamente.", "success")
        elif acao == "compareceu":
            db.atualizar_senha(
                chamada_atual["id"],
                {"resposta": "compareceu", "status": "encerrado", "hora": datetime.now(db.FUSO_HORARIO).isoformat()},
            )
            _notify_painel()
            flash("Senha encerrada como compareceu.", "success")
        elif acao == "nao_compareceu":
            db.atualizar_senha(
                chamada_atual["id"],
                {"resposta": "nao compareceu", "status": "encerrado", "hora": datetime.now(db.FUSO_HORARIO).isoformat()},
            )
            _notify_painel()
            flash("Senha encerrada como nao compareceu.", "info")

        return redirect(url_for("web.chamar"))

    chamada_aberta = db.obter_chamada_aberta()
    fila_ativa = db.obter_fila_ativa()
    data_producao = fila_ativa["data"] if fila_ativa else None
    proxima_senha = db.proxima_senha_aguardando()
    aguardando = db.listar_senhas(
        status="aguardando",
        data_iso=data_producao,
        origem=fila_ativa["origem"] if fila_ativa else None,
    )

    return render_template(
        "_chamar_fila.html" if request.args.get("fragment") == "fila" else "chamar.html",
        usuario=usuario,
        terminal=terminal,
        chamada_aberta=chamada_aberta,
        proxima_senha=proxima_senha,
        aguardando=aguardando,
        total_aguardando=len(aguardando),
        data_producao=data_producao,
        origem_fila_ativa=fila_ativa["origem"] if fila_ativa else None,
        prioridade_labels=PRIORIDADE_LABELS,
    )

@bp.route("/gerar", methods=["GET", "POST"])
def gerar_senhas():
    if request.method == "POST":
        unidade = db.obter_unidade_padrao()
        try:
            senha_inicial = _parse_int_from_form(request.form, "senha_inicial", 1)
            senha_final = _parse_int_from_form(request.form, "senha_final", 50)
        except ValueError as exc:
            field_label = FIELD_LABELS.get(exc.args[0], exc.args[0])
            flash(
                f"O campo {field_label} precisa ser um número inteiro válido.",
                "warning",
            )
            return redirect(url_for("web.gerar_senhas"))
        data_str = request.form.get("data_execucao") or date.today().isoformat()

        try:
            data_escolhida = datetime.strptime(data_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Aviso: informe uma data valida.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        if senha_final < senha_inicial:
            flash("Aviso: a senha final deve ser maior ou igual a inicial.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        if senha_inicial < 1 or senha_final < 1:
            flash("Informe valores positivos para a faixa de senhas.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        inseridas, duplicadas = 0, 0
        iso_data = data_escolhida.isoformat()
        for numero in range(senha_inicial, senha_final + 1):
            if db.senha_existe(numero, iso_data):
                duplicadas += 1
                continue
            db.inserir_senha(numero, unidade, data_execucao=data_escolhida, origem="lote")
            inseridas += 1

        formatted_date = data_escolhida.strftime("%d/%m/%Y")
        if inseridas and db.obter_origem_padrao() != "totem" and not db.obter_data_producao():
            db.definir_data_producao(iso_data)
            db.definir_origem_padrao("lote")
        if inseridas:
            _notify_painel()
            flash(
                f"Sucesso: {inseridas} senhas geradas com sucesso para {formatted_date}.",
                "success",
            )
        if duplicadas:
            flash(
                f"Info: {duplicadas} senhas já existiam para {formatted_date}.",
                "info",
            )

        return redirect(url_for("web.gerar_senhas"))

    total_senhas = db.contar_senhas()
    data_padrao = date.today().isoformat()
    data_producao = db.obter_data_producao_ativa()
    origem_padrao = db.obter_origem_padrao()
    ultimo_normal = db.obter_ultimo_numero_totem("normal")
    ultimo_preferencial = db.obter_ultimo_numero_totem("preferencial")
    remanescentes_normal = db.contar_remanescentes_totem("normal")
    remanescentes_preferencial = db.contar_remanescentes_totem("preferencial")
    sessoes_brutas = db.listar_sessoes_por_data(origem="lote")
    sessoes = []
    for sessao in sessoes_brutas:
        data_iso = sessao.get("data")
        sessoes.append(
            {
                **sessao,
                "data_legivel": _formatar_data_local(data_iso) if data_iso else "",
                "em_producao": origem_padrao == "lote" and data_iso == data_producao,
            }
        )
    return render_template(
        "gerar.html",
        total_senhas=total_senhas,
        data_padrao=data_padrao,
        sessoes=sessoes,
        data_producao=data_producao,
        ultimo_normal=ultimo_normal,
        ultimo_preferencial=ultimo_preferencial,
        remanescentes_normal=remanescentes_normal,
        remanescentes_preferencial=remanescentes_preferencial,
    )


@bp.route("/gerar/definir-producao", methods=["POST"])
def definir_sessao_producao():
    data_str = (request.form.get("data_execucao") or "").strip()
    if not data_str:
        flash("Informe a data da sessão que entrará em produção.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    sessoes = db.listar_sessoes_por_data(origem="lote")
    datas_validas = {sessao.get("data") for sessao in sessoes}
    if data_str not in datas_validas:
        flash("A sessão selecionada não foi encontrada.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    db.definir_data_producao(data_str)
    db.definir_origem_padrao("lote")
    _notify_painel()
    flash(
        f"Sessão de {datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')} marcada como em produção.",
        "success",
    )
    return redirect(url_for("web.gerar_senhas"))


@bp.route("/gerar/excluir-sessao", methods=["POST"])
def excluir_sessao_senhas():
    data_str = (request.form.get("data_execucao") or "").strip()
    if not data_str:
        flash("Informe a data da sessão que deseja remover.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    try:
        data_formatada = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Informe uma data válida.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    removidas = db.excluir_senhas_por_data(data_str)
    if removidas:
        _notify_painel()
        flash(
            f"Sessão de {data_formatada.strftime('%d/%m/%Y')} removida ({removidas} senhas).",
            "success",
        )
    else:
        flash("Nenhuma senha encontrada para essa data.", "info")

    return redirect(url_for("web.gerar_senhas"))


@bp.route("/gerar/reiniciar-totem", methods=["POST"])
def reiniciar_totem():
    prioridade = (request.form.get("prioridade") or "").strip().lower()
    if prioridade not in PRIORIDADE_LABELS:
        flash("Prioridade invalida para reinicio.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    remover_remanescentes = request.form.get("remover_remanescentes") == "1"
    removidas = 0
    if remover_remanescentes:
        removidas = db.excluir_remanescentes_totem(prioridade)

    db.reiniciar_numero_totem(prioridade)
    if remover_remanescentes:
        _notify_painel()
        flash(
            f"Contador de {PRIORIDADE_LABELS[prioridade].lower()} reiniciado e {removidas} senha(s) remanescente(s) removida(s).",
            "success",
        )
    else:
        flash(f"Contador de {PRIORIDADE_LABELS[prioridade].lower()} reiniciado.", "success")
    return redirect(url_for("web.gerar_senhas"))


@bp.route("/historico", methods=["GET", "POST"])
def historico():
    registros = db.listar_todas_senhas()
    sessoes_brutas = db.listar_sessoes_por_data(origem="lote")
    sessoes = []
    for sessao in sessoes_brutas:
        data_iso = sessao.get("data")
        sessoes.append(
            {
                **sessao,
                "data_legivel": _formatar_data_local(data_iso) if data_iso else "",
            }
        )
    sessao_padrao = sessoes[0]["data"] if sessoes else None
    sessao_data = request.args.get("sessao_data") or sessao_padrao

    if request.method == "POST":
        acao = (request.form.get("acao") or "").strip().lower()
        if acao == "encerrar_sequencia":
            inicio_raw = (request.form.get("senha_inicio") or "").strip()
            final_raw = (request.form.get("senha_final") or "").strip()
            if not inicio_raw.isdigit() or not final_raw.isdigit():
                flash("Informe valores inteiros vÃ¡lidos para o intervalo.", "warning")
                return redirect(url_for("web.historico"))

            inicio = int(inicio_raw)
            final = int(final_raw)
            if inicio < 1 or final < 1:
                flash("Os nÃºmeros devem ser positivos.", "warning")
                return redirect(url_for("web.historico"))
            if final < inicio:
                flash("A senha final precisa ser maior que a inicial.", "warning")
                return redirect(url_for("web.historico"))

            sessao_data = (request.form.get("sessao_data") or sessao_padrao)
            if not sessao_data:
                flash("Selecione a sessão que deseja encerrar.", "warning")
                return redirect(url_for("web.historico"))

            encerradas = db.encerrar_sequencia_senhas(inicio, final, data_iso=sessao_data)
            if encerradas:
                _notify_painel()
            if not encerradas:
                flash(
                    "Nenhuma senha aguardando foi encontrada nesse intervalo.",
                    "info",
                )
            else:
                flash(
                    f"{encerradas} senhas encerradas da faixa {inicio}-{final} do dia {datetime.strptime(sessao_data, '%Y-%m-%d').strftime('%d/%m/%Y')}",
                    "success",
                )
            return redirect(url_for("web.historico", sessao_data=sessao_data))

        encerrar_id = (request.form.get("encerrar_id") or "").strip()
        if not encerrar_id.isdigit():
            flash("Informe um ID valido para encerrar.", "warning")
            return redirect(url_for("web.historico"))

        encerrar_id = int(encerrar_id)
        alvo = next((r for r in registros if r["id"] == encerrar_id), None)
        if not alvo:
            flash("Senha nao encontrada.", "warning")
            return redirect(url_for("web.historico"))
        if (alvo.get("status") or "").lower() != "aberto":
            flash("A senha selecionada ja estava encerrada.", "info")
            return redirect(url_for("web.historico"))

        acao = (acao or "nao_compareceu").strip().lower()
        if acao != "compareceu":
            acao = "nao_compareceu"
        resposta_padrao = "compareceu" if acao == "compareceu" else "nao compareceu"
        mensagem = (
            "Senha encerrada como compareceu."
            if acao == "compareceu"
            else "Senha encerrada como nao compareceu."
        )
        db.encerrar_senha(encerrar_id, resposta_padrao=resposta_padrao)
        _notify_painel()
        flash(mensagem, "success")
        return redirect(url_for("web.historico"))

    status_counts = Counter(
        (registro.get("status") or "sem status").capitalize() for registro in registros
    )
    resposta_counts = Counter(
        (registro.get("resposta") or "sem resposta").capitalize() for registro in registros
        if registro.get("resposta")
    )
    usuario_counts = Counter(
        registro.get("usuario").strip()
        for registro in registros
        if registro.get("usuario")
        and registro.get("usuario").strip().lower() != DEFAULT_USUARIO
    )

    abertas = [
        {
            **registro,
            "hora_legivel": _formatar_data_hora(registro.get("hora")),
        }
        for registro in registros
        if (registro.get("status") or "").lower() == "aberto"
    ]
    encerradas = [
        {
            **registro,
            "hora_legivel": _formatar_data_hora(registro.get("hora")),
        }
        for registro in registros
        if (registro.get("status") or "").lower() == "encerrado"
    ][:20]

    sessao_data_label = _formatar_data_local(sessao_data) if sessao_data else ""
    return render_template(
        "historico.html",
        status_labels=list(status_counts.keys()),
        status_values=list(status_counts.values()),
        resposta_labels=list(resposta_counts.keys()),
        resposta_values=list(resposta_counts.values()),
        usuario_labels=list(usuario_counts.keys()),
        usuario_values=list(usuario_counts.values()),
        abertas=abertas,
        encerradas=encerradas,
        sessoes=sessoes,
        sessao_data=sessao_data,
        sessao_data_label=sessao_data_label,
    )


@bp.route("/painel/compacto")
def painel_compacto():
    return render_template("painel_compacto.html", cores=cores_painel_da_unidade())


@bp.route("/painel")
def painel():
    unidade = g.get("unidade")
    link = obter_link_painel(unidade["id"]) if unidade else ""
    return render_template("painel.html", video_embed=_montar_video_embed(link), cores=cores_painel_da_unidade(),
                           logo=obter_logo_painel(unidade["id"]) if unidade else None)


@bp.route("/senhas")
def senhas():
    return render_template("senhas.html")


@bp.post("/senhas/emitir/<prioridade>")
def emitir_senha(prioridade: str):
    prioridade = prioridade.strip().lower()
    if prioridade not in PRIORIDADE_LABELS:
        return jsonify(ok=False, message="Tipo de senha inválido."), 400

    try:
        identificador, numero_int = db.emitir_senha_totem(prioridade)
    except db.LimitePreferencial:
        return jsonify(ok=False, message="A fila preferencial atingiu o limite 100. Reinicie o contador para voltar ao 001."), 409

    _notify_painel()
    numero = f"{numero_int:03}"
    return jsonify(ok=True, message=f"{PRIORIDADE_LABELS[prioridade]} {numero} emitida.", senha=numero,
                   prioridade=prioridade, id=identificador)


@bp.route("/painel/status")
def painel_status():
    return jsonify(db.obter_painel_status_snapshot(MAX_PAINEL_ULTIMAS))


@bp.route("/painel/events")
def painel_events():
    app = current_app._get_current_object()
    events = g.get("painel_events", app.extensions["painel_events"])
    db_path = g.get("db_path")

    def load_snapshot():
        # Apenas a leitura precisa do contexto; nao retem a requisicao
        # ou uma conexao SQLite durante a espera por notificacoes.
        with app.app_context():
            if db_path is not None:
                g.db_path = db_path
            return db.obter_painel_status_snapshot(MAX_PAINEL_ULTIMAS)

    return Response(
        events.stream(load_snapshot),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _formatar_data_local(valor_iso: str | None) -> str:
    """Formata data ISO armazenada no banco para exibicao local."""
    dt = _converter_para_local(valor_iso)
    return dt.strftime("%d/%m/%Y")

def _formatar_data_hora(valor_iso: str | None) -> str:
    """Formata data e hora para exibiÃ§Ã£o completa."""
    dt = _converter_para_local(valor_iso)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def _extrair_data_iso(valor_iso: str | None) -> str:
    """Retorna a data YYYY-MM-DD correspondente ao registro."""
    return _converter_para_local(valor_iso).date().isoformat()


def _converter_para_local(valor_iso: str | None) -> datetime:
    """Converte uma string ISO do banco para datetime no fuso configurado."""
    if not valor_iso:
        return datetime.now(db.FUSO_HORARIO)

    try:
        dt = datetime.fromisoformat(valor_iso)
    except ValueError:
        return datetime.now(db.FUSO_HORARIO)

    if dt.tzinfo is None:
        dt = db.FUSO_HORARIO.localize(dt)
    else:
        dt = dt.astimezone(db.FUSO_HORARIO)

    return dt


def _parse_int_from_form(form, campo, default):
    """Retorna um inteiro simples do formulario com fallback."""
    raw = (form.get(campo) or str(default)).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(campo)


def _notify_painel():
    g.get("painel_events", current_app.extensions["painel_events"]).publish(
        lambda: db.obter_painel_status_snapshot(MAX_PAINEL_ULTIMAS)
    )


def _resolver_playlist_id(valor: str | None) -> str:
    if not valor:
        return DEFAULT_PLAYLIST_ID
    alvo = valor.strip()
    if "://" in alvo:
        parsed = urlparse(alvo)
        query = parse_qs(parsed.query)
        candidato = query.get("list", [None])[0]
        if candidato:
            return candidato
        segmentos = [seg for seg in parsed.path.split("/") if seg]
        if segmentos:
            return segmentos[-1]
        ident = parsed.path.rstrip("/").split("/")[-1]
        if ident:
            return ident
    return alvo


def _montar_video_embed(link_youtube: str = "") -> str:
    yt_muted = os.getenv("PAINEL_YT_MUTED", "1") not in {"0", "false", "no", "off"}
    origem_youtube = painel_youtube.origem_embed(link_youtube, yt_muted) if link_youtube else None
    if origem_youtube:
        return _iframe_youtube(origem_youtube)

    url = (os.getenv("PAINEL_VIDEO_URL") or "").strip()
    if url:
        lower = url.lower()
        if lower.endswith((".mp4", ".webm", ".ogg")):
            muted_flag = os.getenv("PAINEL_VIDEO_MUTED", "1") not in {"0", "false", "no", "off"}
            mute_attr = " muted" if muted_flag else ""
            return (
                '<video src="{url}" autoplay loop playsinline{mute} '
                'style="width:100%;height:100%;object-fit:cover;background:#000;" controls></video>'
            ).format(url=url, mute=mute_attr)
        return (
            '<iframe src="{url}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            'gyroscope; picture-in-picture; fullscreen" allowfullscreen '
            'style="width:100%;height:100%;border:0;background:#000;"></iframe>'
        ).format(url=url)

    playlist = _resolver_playlist_id(
        os.getenv("PAINEL_YT_PLAYLIST_URL")
        or os.getenv("PAINEL_YT_PLAYLIST_ID")
        or DEFAULT_PLAYLIST_ID
    )
    return _iframe_youtube(painel_youtube.origem_playlist(playlist, yt_muted))


def _iframe_youtube(origem):
    return (
        '<iframe '
        'src="{origem}" '
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen" '
        'referrerpolicy="strict-origin-when-cross-origin" '
        'allowfullscreen '
        'style="width:100%;height:100%;border:0;background:#000;" '
        'title="Painel - YouTube"></iframe>'
    ).format(origem=origem)


