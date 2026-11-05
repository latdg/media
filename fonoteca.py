#!/usr/bin/env python3
# =============================================================================
# LA TdG FONOTECA — arxiu permanent dels àudios de «declaracions» (05.11.2026)
#
# Mode «explora»: només llegeix la carpeta del disc dur i diu què hi ha
#                 (noms, mides, dates). No baixa ni comprimeix res.
# Mode «arxiva»:  baixa els àudios nous, els comprimeix per a veu i els desa
#                 a la carpeta de sortida amb l'inventari (inventari.json).
#
# L'adreça del disc dur i les credencials arriben com a secrets i no
# s'escriuen MAI als registres (tot el que surt passa per «amaga()»).
# =============================================================================
import json, os, re, subprocess, sys, time, unicodedata, html
import urllib.parse, urllib.request, base64
from email.utils import parsedate_to_datetime

AUDIO = (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".flac", ".wma", ".amr", ".3gp", ".mp4", ".webm")
# .mp4 i .webm només si són dins de la carpeta d'àudios (sovint són notes de veu del mòbil).

BASE = re.sub(r"[\r\n\t \"'`<>]", "", os.environ.get("MEDIA_SERVER_BASE", ""))
if BASE and not BASE.startswith(("http://", "https://")):
    BASE = "http://" + BASE
if not BASE.endswith("/"):
    BASE += "/"
USUARI = os.environ.get("MEDIA_SERVER_USER", "")
CONTRA = os.environ.get("MEDIA_SERVER_PASSWORD", "")
AUTH = "Basic " + base64.b64encode((USUARI + ":" + CONTRA).encode()).decode()
HOST = urllib.parse.urlsplit(BASE).netloc


def amaga(text):
    """Treu l'adreça del disc dur de qualsevol text que s'hagi d'escriure."""
    t = str(text)
    if HOST:
        t = t.replace(HOST, "[disc]")
        t = t.replace(urllib.parse.urlsplit(BASE).hostname or "\u0000", "[disc]")
    return t


def demana(url, metode="GET", temps=60):
    req = urllib.request.Request(url, method=metode, headers={"Authorization": AUTH, "User-Agent": "LaTdG-fonoteca/1.0"})
    return urllib.request.urlopen(req, timeout=temps)


def llista(url, profunditat=0, max_prof=5, vistos=None):
    """Llegeix el llistat HTML d'una carpeta i hi entra recursivament."""
    vistos = vistos if vistos is not None else set()
    if url in vistos or profunditat > max_prof:
        return []
    vistos.add(url)
    cos, hrefs = None, []
    try:
        with demana(url) as r:
            cos = r.read().decode("utf-8", "replace")
            hrefs = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', cos, re.I)
    except Exception as e:
        print("  · GET", amaga(rel(url)), "→", amaga(e))
    if not hrefs:
        # El servidor no dona llistat HTML: provem WebDAV (PROPFIND).
        try:
            req = urllib.request.Request(url, method="PROPFIND", data=b'<?xml version="1.0"?><propfind xmlns="DAV:"><allprop/></propfind>',
                                         headers={"Authorization": AUTH, "Depth": "1", "Content-Type": "application/xml", "User-Agent": "LaTdG-fonoteca/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                cos = r.read().decode("utf-8", "replace")
            hrefs = [urllib.parse.urljoin(url, h) for h in re.findall(r"<(?:\w+:)?href>([^<]+)</(?:\w+:)?href>", cos, re.I)]
            print("  · WebDAV", amaga(rel(url)), "→", len(hrefs), "entrades")
            if not hrefs:
                sonda_webdav(url)
        except Exception as e:
            print("  ⚠️ No es pot llistar", amaga(rel(url)), "(ni GET ni WebDAV) →", amaga(e))
            return []
    sortida = []
    for href in hrefs:
        href = html.unescape(href)
        if href.startswith(("?", "#", "javascript:", "mailto:")):
            continue
        absoluta = urllib.parse.urljoin(url, href)
        if not absoluta.startswith(url) or absoluta == url:
            continue  # pares, enllaços d'ordenació o externs
        if absoluta.endswith("/"):
            sortida += llista(absoluta, profunditat + 1, max_prof, vistos)
        elif absoluta.lower().endswith(AUDIO):
            sortida.append(absoluta)
    return sorted(set(sortida))


def sonda_webdav(url):
    """Diagnòstic: prova variants de PROPFIND i diu què respon el servidor."""
    variants = [("sense cos, Depth 1", None, "1"), ("propname", b'<?xml version="1.0" encoding="utf-8"?><D:propfind xmlns:D="DAV:"><D:propname/></D:propfind>', "1"),
                ("prop concrets", b'<?xml version="1.0" encoding="utf-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:displayname/><D:getcontentlength/><D:getlastmodified/><D:resourcetype/></D:prop></D:propfind>', "1"),
                ("sense cos, Depth 0", None, "0")]
    for nom, cos, depth in variants:
        for u in (url, url.rstrip("/")):
            try:
                h = {"Authorization": AUTH, "Depth": depth, "User-Agent": "LaTdG-fonoteca/1.0"}
                if cos: h["Content-Type"] = "text/xml; charset=utf-8"
                req = urllib.request.Request(u, method="PROPFIND", data=cos, headers=h)
                with urllib.request.urlopen(req, timeout=60) as r:
                    b = r.read()
                    print("    ·", nom, "/" if u.endswith("/") else "sense /", "→", r.status, len(b), "bytes", amaga(b[:400].decode("utf-8", "replace")).replace("\n", " "))
            except Exception as e:
                print("    ·", nom, "→", amaga(e))


def rel(url):
    return urllib.parse.unquote(url[len(BASE):]) if url.startswith(BASE) else urllib.parse.unquote(url)


def capcalera(url):
    try:
        with demana(url, "HEAD", 30) as r:
            mida = int(r.headers.get("Content-Length") or 0)
            lm = r.headers.get("Last-Modified")
            data = parsedate_to_datetime(lm).strftime("%Y-%m-%d") if lm else ""
            return mida, data
    except Exception:
        return 0, ""


def data_del_nom(nom):
    """20261103evigo.mp3 → 2026-11-03 ; també 2026-11-03, 03.11.2026, 03-11-2026."""
    m = re.search(r"(20\d\d)[-_.]?([01]\d)[-_.]?([0-3]\d)", nom)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return "%s-%s-%s" % m.groups()
    m = re.search(r"([0-3]\d)[-_.]([01]\d)[-_.](20\d\d)", nom)
    if m and 1 <= int(m.group(2)) <= 12:
        return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
    return ""


def slug(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:80] or "audio"


def durada(fitxer):
    try:
        s = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", fitxer],
                           capture_output=True, text=True, timeout=60).stdout.strip()
        return int(float(s))
    except Exception:
        return 0


# -----------------------------------------------------------------------------
def explora(carpetes):
    print("Exploració de la fonoteca (no es baixa ni es comprimeix res)\n")
    resum = []
    for c in carpetes:
        url = urllib.parse.urljoin(BASE, c)
        print("== Carpeta:", amaga(rel(url) or c))
        try:
            with demana(url, "OPTIONS", 30) as r:
                print("  · Servidor:", amaga(r.headers.get("Server")), "· mètodes:", r.headers.get("Allow") or r.headers.get("DAV") or "?")
        except Exception as e:
            print("  · OPTIONS →", amaga(e), "· Servidor:", amaga(getattr(e, "headers", {}).get("Server") if hasattr(e, "headers") else ""))
        fitxers = llista(url)
        total = 0
        anys = {}
        for f in fitxers:
            mida, data = capcalera(f)
            total += mida
            any_ = (data_del_nom(f.rsplit("/", 1)[-1]) or data)[:4] or "????"
            anys[any_] = anys.get(any_, 0) + 1
            print("   %8.1f MB  %s  %s" % (mida / 1048576, data or "          ", amaga(rel(f))))
        print("   → %d àudios, %.1f MB en total; per anys: %s\n" % (len(fitxers), total / 1048576, json.dumps(dict(sorted(anys.items())))))
        resum.append({"carpeta": c, "audios": len(fitxers), "mb": round(total / 1048576, 1), "anys": anys})
    with open("exploracio.json", "w") as f:
        json.dump(resum, f, ensure_ascii=False, indent=1)


# -----------------------------------------------------------------------------
def arxiva(carpetes, sortida, max_minuts, kbps):
    os.makedirs(sortida, exist_ok=True)
    cami_inv = os.path.join(sortida, "inventari.json")
    inv = {"audios": []}
    if os.path.exists(cami_inv):
        with open(cami_inv) as f:
            inv = json.load(f)
    per_origen = {a["origen"]: a for a in inv["audios"]}
    ids = {a["id"] for a in inv["audios"]}
    inici = time.time()
    nous = 0
    presents = set()

    for c in carpetes:
        for url in llista(urllib.parse.urljoin(BASE, c)):
            origen = rel(url)
            presents.add(origen)
            if origen in per_origen:
                continue
            if time.time() - inici > max_minuts * 60:
                print("⏱️ S'ha arribat al límit de temps d'aquesta passada; la resta, a la propera.")
                break
            nom = origen.rsplit("/", 1)[-1]
            base_id = slug(nom.rsplit(".", 1)[0])
            ident, n = base_id, 2
            while ident in ids:
                ident, n = "%s-%d" % (base_id, n), n + 1
            mida_orig, data_fitxer = capcalera(url)
            print("➕", amaga(origen), "(%.1f MB)" % (mida_orig / 1048576))
            try:
                subprocess.run(["curl", "-fsS", "--retry", "3", "--max-time", "1800", "-u", USUARI + ":" + CONTRA,
                                "-o", "original", url], check=True, stderr=subprocess.DEVNULL)
            except Exception:
                print("   ⚠️ No s'ha pogut baixar; es tornarà a provar la propera vegada.")
                continue
            dur = durada("original")
            desti = os.path.join(sortida, ident + ".mp3")
            ordre = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "original", "-vn",
                     "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1", "-ar", "32000",
                     "-c:a", "libmp3lame", "-b:a", "%dk" % kbps, desti]
            if subprocess.run(ordre).returncode != 0:
                ordre.remove("-af"); ordre.remove("loudnorm=I=-16:TP=-1.5:LRA=11")
                if subprocess.run(ordre).returncode != 0:
                    print("   ⚠️ ffmpeg no l'ha pogut convertir; es deixa estar.")
                    continue
            os.remove("original")
            entrada = {
                "id": ident,
                "origen": origen,
                "fitxer": ident + ".mp3",
                "durada": dur or durada(desti),
                "mida": os.path.getsize(desti),
                "data": data_del_nom(nom) or data_fitxer,
                "data_fitxer": data_fitxer,
                "afegit": time.strftime("%Y-%m-%d"),
            }
            inv["audios"].append(entrada)
            per_origen[origen] = entrada
            ids.add(ident)
            nous += 1
            print("   ✅ %s · %d min · %.1f MB" % (entrada["fitxer"], entrada["durada"] // 60, entrada["mida"] / 1048576))

    # Si l'original ja no és al disc dur, la còpia de la fonoteca es manté.
    for a in inv["audios"]:
        a["origen_absent"] = (a["origen"] not in presents) if presents else a.get("origen_absent", False)
    inv["actualitzat"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    inv["total_mb"] = round(sum(a["mida"] for a in inv["audios"]) / 1048576, 1)
    inv["audios"].sort(key=lambda a: (a.get("data") or "", a["id"]), reverse=True)
    with open(cami_inv, "w") as f:
        json.dump(inv, f, ensure_ascii=False, indent=1)
    print("\nNous: %d · A la fonoteca: %d àudios, %.1f MB" % (nous, len(inv["audios"]), inv["total_mb"]))
    if inv["total_mb"] > 850:
        print("::warning::La fonoteca ja ocupa %.0f MB (GitHub Pages admet fins a 1 GB)." % inv["total_mb"])


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "explora"
    carpetes = [c.strip() for c in os.environ.get("FONOTECA_CARPETES", "declaracions/").split(",") if c.strip()]
    if not BASE.strip("/"):
        sys.exit("Falta MEDIA_SERVER_BASE")
    if mode == "explora":
        explora(carpetes)
    else:
        arxiva(carpetes, os.environ.get("FONOTECA_SORTIDA", "fonoteca/f"),
               int(os.environ.get("FONOTECA_MAX_MINUTS", "300")), int(os.environ.get("FONOTECA_KBPS", "48")))
