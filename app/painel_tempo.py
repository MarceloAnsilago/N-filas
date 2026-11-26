import json
from pathlib import Path


UF_PADRAO = "11"
MUNICIPIO_PADRAO = "1100320"
# Catálogo de https://github.com/kelvins/municipios-brasileiros (MIT).
ESTADOS = json.loads((Path(__file__).parent / "static" / "municipios.json").read_text(encoding="utf-8"))


def ler_local(conn, unidade_id):
    row = conn.execute(
        "SELECT municipio FROM painel_tempo WHERE unidade_id = ?", (unidade_id,)
    ).fetchone()
    return local_municipio(row["municipio"] if row else MUNICIPIO_PADRAO)


def local_municipio(municipio=MUNICIPIO_PADRAO):
    uf = municipio[:2]
    estado = ESTADOS.get(uf)
    if not estado or municipio not in estado["municipios"]:
        uf, municipio = UF_PADRAO, MUNICIPIO_PADRAO
        estado = ESTADOS[uf]
    return dict(estado["municipios"][municipio], uf=uf, id=municipio, sigla=estado["sigla"])
