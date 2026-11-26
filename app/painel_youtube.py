import re
from urllib.parse import parse_qs, urlencode, urlsplit


def origem_playlist(playlist, muted):
    return (
        f"https://www.youtube-nocookie.com/embed/videoseries?list={playlist}"
        f"&autoplay=1&loop=1&playsinline=1&rel=0&modestbranding=1&mute={int(muted)}"
    )


def origem_embed(link, muted):
    try:
        url = urlsplit(link)
    except ValueError:
        return None
    if url.scheme not in {"https", "http"}:
        return None

    caminho = url.path.strip("/").split("/")
    parametros = parse_qs(url.query)
    playlist = parametros.get("list", [""])[0]
    video = ""
    if url.netloc.lower() == "youtu.be" and len(caminho) == 1:
        video = caminho[0]
    elif url.netloc.lower() in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if caminho == ["watch"]:
            video = parametros.get("v", [""])[0]
        elif len(caminho) == 2 and caminho[0] in {"embed", "shorts", "live"}:
            video = caminho[1]
        elif caminho != ["playlist"]:
            return None
    else:
        return None

    opcoes = {"autoplay": 1, "loop": 1, "playsinline": 1, "rel": 0, "mute": int(muted)}
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", playlist):
        return origem_playlist(playlist, muted)
    elif re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        destino = f"https://www.youtube-nocookie.com/embed/{video}"
        opcoes["playlist"] = video
    else:
        return None
    return f"{destino}?{urlencode(opcoes)}"
