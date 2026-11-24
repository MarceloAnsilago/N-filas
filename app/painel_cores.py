import re


# Chave CSS, rótulo no formulário e cor inicial do seletor.
ITENS = (
    ("fundo", "Fundo do painel", "#032241"),
    ("texto", "Texto geral e relógio", "#ffffff"),
    ("cabecalho", "Cabeçalho", "#052343"),
    ("video", "Fundo da área de vídeo", "#20496a"),
    ("chamada", "Cartão da chamada atual", "#ffffff"),
    ("chamada-texto", "Texto da chamada atual", "#092855"),
    ("senha", "Número da senha chamada", "#0046d1"),
    ("guiche", "Fundo do guichê", "#c8efee"),
    ("guiche-numero", "Número e ícone do guichê", "#00953c"),
    ("fila", "Área de próximas senhas", "#ffffff"),
    ("fila-texto", "Texto das próximas senhas", "#092855"),
    ("fila-cartao", "Cartões da fila", "#ffffff"),
    ("fila-proxima", "Cartão da próxima chamada", "#e1efff"),
    ("normal", "Ícone de senha normal", "#2dafff"),
    ("preferencial", "Ícone de senha preferencial", "#ffb62d"),
    ("clima", "Área de previsão do tempo", "#06264b"),
    ("clima-texto", "Texto da previsão do tempo", "#ffffff"),
    ("historico", "Cartões do histórico", "#07385f"),
    ("historico-texto", "Texto dos cartões do histórico", "#ffffff"),
    ("compareceu", "Indicador de comparecimento", "#8cf0c4"),
    ("ausente", "Indicador de ausência", "#ffb4b4"),
    ("rodape", "Rodapé", "#021d39"),
    ("rodape-texto", "Texto do rodapé", "#ffffff"),
)


def ler_cores(conn, unidade_id):
    return dict(conn.execute(
        "SELECT item, cor FROM painel_cor WHERE unidade_id = ?", (unidade_id,)
    ).fetchall())


def validar_cores(form):
    cores = {}
    for chave, _, padrao in ITENS:
        cor = form.get(chave, "").lower()
        if re.fullmatch(r"#[0-9a-f]{6}", cor) is None:
            return None
        if cor != padrao:
            cores[chave] = cor
    return cores


def gravar_cores(conn, unidade_id, cores):
    conn.execute("DELETE FROM painel_cor WHERE unidade_id = ?", (unidade_id,))
    conn.executemany(
        "INSERT INTO painel_cor (unidade_id, item, cor) VALUES (?, ?, ?)",
        ((unidade_id, item, cor) for item, cor in cores.items()),
    )
