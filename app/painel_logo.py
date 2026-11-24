from io import BytesIO
import warnings

from PIL import Image, ImageOps


MAX_ARQUIVO = 5 * 1024 * 1024


def preparar_logo(arquivo):
    if not arquivo or not arquivo.filename:
        raise ValueError("Escolha uma imagem PNG, JPEG ou WebP.")
    dados = arquivo.stream.read(MAX_ARQUIVO + 1)
    if len(dados) > MAX_ARQUIVO:
        raise ValueError("A imagem deve ter no máximo 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(dados), formats=("PNG", "JPEG", "WEBP")) as imagem:
                if imagem.width * imagem.height > 16_000_000:
                    raise ValueError("A imagem deve ter no máximo 16 megapixels.")
                imagem = ImageOps.exif_transpose(imagem)
                imagem.thumbnail((1200, 500))
                saida = BytesIO()
                imagem.convert("RGBA").save(saida, format="PNG")
                return saida.getvalue()
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as erro:
        raise ValueError("Envie uma imagem PNG, JPEG ou WebP válida.") from erro
