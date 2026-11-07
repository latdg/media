#!/usr/bin/env python3
# =============================================================================
# LA TdG FONOTECA — arxiu permanent dels àudios de «declaracions» (05.11.2026)
#
# El disc dur no deixa llistar carpetes, així que la fonoteca no busca a
# cegues: arxiva NOMÉS els àudios que el publicador ja ha difós (registre.tsv
# de la branca «fitxers»). Entren sols, amb la fitxa que s'omple al publicador.
#
# 07.11.2026: ja no s'afegeixen àudios a mà des de la pàgina La TdG fonoteca
# (abans, amb el nom del fitxer de /xarxes/declaracions/). Del catàleg
# (dades/fonoteca.json de latdg/tauler) només es llegeixen els eliminats.
#
# Per a cada àudio que encara no té: el baixa del disc dur, el comprimeix per
# a veu (MP3 mono, volum igualat a -16 LUFS) i el desa a la carpeta de sortida
# amb l'inventari (inventari.json): durada, mida i data.
#
# Aquí no s'esborra mai res. L'adreça del disc dur i les credencials arriben
# com a secrets i no s'escriuen MAI als registres (tot passa per «amaga()»).
# =============================================================================
import json, os, re, subprocess, sys, time, unicodedata
import urllib.parse, urllib.request, base64
from email.utils import parsedate_to_datetime

CATALEG_URL = "https://raw.githubusercontent.com/latdg/tauler/main/dades/fonoteca.json"
CARPETA = "declaracions/"

BASE = re.sub(r"[\r\n\t \"'`<>]", "", os.environ.get("MEDIA_SERVER_BASE", ""))
if BASE and not BASE.startswith(("http://", "https://")):
    BASE = "http://" + BASE
if not BASE.endswith("/"):
    BASE += "/"
USUARI = os.environ.get("MEDIA_SERVER_USER", "")
CONTRA = os.environ.get("MEDIA_SERVER_PASSWORD", "")
AUTH = "Basic " + base64.b64encode((USUARI + ":" + CONTRA).encode()).decode()
_parts = urllib.parse.urlsplit(BASE)


def amaga(text):
    t = str(text)
    for h in (_parts.netloc, _parts.hostname):
        if h:
            t = t.replace(h, "[disc]")
    return t


def url_de(nom):
    return BASE + urllib.parse.quote(CARPETA + nom)


def capcalera(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"Authorization": AUTH, "User-Agent": "LaTdG-fonoteca/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            lm = r.headers.get("Last-Modified")
            return True, (parsedate_to_datetime(lm).strftime("%Y-%m-%d") if lm else "")
    except urllib.error.HTTPError as e:
        return (e.code != 404), ""
    except Exception:
        return True, ""


def data_del_nom(nom):
    """20261103evigo.mp3 → 2026-11-03 (també 2026-11-03… i 03.11.2026…)."""
    m = re.search(r"(20\d\d)[-_.]?([01]\d)[-_.]?([0-3]\d)", nom)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return "%s-%s-%s" % m.groups()
    m = re.search(r"([0-3]\d)[-_.]([01]\d)[-_.](20\d\d)", nom)
    if m and 1 <= int(m.group(2)) <= 12:
        return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
    return ""


def slug(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80] or "audio"


def durada(fitxer):
    try:
        s = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", fitxer],
                           capture_output=True, text=True, timeout=60).stdout.strip()
        return int(float(s))
    except Exception:
        return 0


def demanats(registre):
    """Noms de fitxer que han d'entrar a la fonoteca (els que ha difós el
    publicador), i els eliminats a la pàgina. Si no es pot llegir el catàleg,
    eliminats és None (llavors no s'esborra res)."""
    noms, eliminats = [], set()
    try:
        with urllib.request.urlopen(CATALEG_URL + "?t=%d" % time.time(), timeout=30) as r:
            for a in json.load(r).get("audios", []):
                nom = (a.get("fitxer") or "").strip().split("/")[-1]
                if not nom:
                    continue
                # 07.11.2026: les fitxes del catàleg ja no fan entrar cap àudio.
                if a.get("eliminat"):
                    eliminats.add(nom)
    except Exception as e:
        print("⚠️ No s'ha pogut llegir el catàleg de la fonoteca:", e)
        eliminats = None
    if registre and os.path.exists(registre):
        for linia in open(registre, encoding="utf-8"):
            parts = linia.rstrip("\n").split("\t")
            if len(parts) > 1 and parts[1].startswith("a/"):
                noms.append(parts[1][2:])
    vist, sortida = set(), []
    for n in noms:
        if n and n not in vist and not (eliminats and n in eliminats):
            vist.add(n)
            sortida.append(n)
    return sortida, eliminats


def arxiva(sortida, registre, max_minuts, kbps):
    os.makedirs(sortida, exist_ok=True)
    cami_inv = os.path.join(sortida, "inventari.json")
    inv = {"audios": []}
    if os.path.exists(cami_inv):
        inv = json.load(open(cami_inv, encoding="utf-8"))
    per_nom = {a["fitxer_original"]: a for a in inv["audios"]}
    ids = {a["id"] for a in inv["audios"]}
    no_trobats = []
    inici, nous = time.time(), 0
    noms, eliminats = demanats(registre)

    # 05.11.2026: àudios eliminats a la pàgina. Es treu la còpia de la
    # fonoteca (GitHub); l'original del disc dur NO es toca mai.
    if eliminats is not None:
        for nom in sorted(eliminats):
            a = per_nom.pop(nom, None)
            if a:
                try:
                    os.remove(os.path.join(sortida, a["fitxer"]))
                except FileNotFoundError:
                    pass
                inv["audios"] = [x for x in inv["audios"] if x["fitxer_original"] != nom]
                print("🗑️ Eliminat de la fonoteca:", nom, "(l'original del disc dur es manté)")
        inv["eliminats"] = sorted(eliminats)

    for nom in noms:
        if nom in per_nom:
            continue
        if time.time() - inici > max_minuts * 60:
            print("⏱️ Límit de temps d'aquesta passada; la resta, a la propera.")
            break
        url = url_de(nom)
        existeix, data_fitxer = capcalera(url)
        if not existeix:
            no_trobats.append(nom)
            continue
        print("➕", nom)
        try:
            subprocess.run(["curl", "-fsS", "--retry", "3", "--max-time", "1800", "-u", USUARI + ":" + CONTRA, "-o", "original", url],
                           check=True, stderr=subprocess.DEVNULL)
        except Exception:
            print("   ⚠️ No s'ha pogut baixar; es tornarà a provar a la propera passada.")
            continue
        base_id = slug(nom.rsplit(".", 1)[0])
        ident, n = base_id, 2
        while ident in ids:
            ident, n = "%s-%d" % (base_id, n), n + 1
        desti = os.path.join(sortida, ident + ".mp3")
        ordre = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "original", "-vn",
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1", "-ar", "44100",
                 "-c:a", "libmp3lame", "-b:a", "%dk" % kbps, desti]
        if subprocess.run(ordre).returncode != 0:
            del ordre[8:10]
            if subprocess.run(ordre).returncode != 0:
                print("   ⚠️ ffmpeg no l'ha pogut convertir.")
                continue
        entrada = {
            "id": ident,
            "fitxer_original": nom,
            "fitxer": ident + ".mp3",
            "durada": durada("original") or durada(desti),
            "mida": os.path.getsize(desti),
            "data": data_del_nom(nom) or data_fitxer,
            "afegit": time.strftime("%Y-%m-%d"),
        }
        os.remove("original")
        inv["audios"].append(entrada)
        per_nom[nom] = entrada
        ids.add(ident)
        nous += 1
        print("   ✅ %s · %d:%02d · %.1f MB" % (entrada["fitxer"], entrada["durada"] // 60, entrada["durada"] % 60, entrada["mida"] / 1048576))

    inv["no_trobats"] = no_trobats
    inv["total_mb"] = round(sum(a["mida"] for a in inv["audios"]) / 1048576, 1)
    inv["audios"].sort(key=lambda a: (a.get("data") or "", a["id"]), reverse=True)
    if nous or "actualitzat" not in inv:
        inv["actualitzat"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(inv, open(cami_inv, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if no_trobats:
        print("🔎 No són a /xarxes/declaracions/:", ", ".join(no_trobats))
    print("Nous: %d · A la fonoteca: %d àudios, %.1f MB" % (nous, len(inv["audios"]), inv["total_mb"]))
    if inv["total_mb"] > 850:
        print("::warning::La fonoteca ja ocupa %.0f MB (GitHub Pages admet fins a 1 GB)." % inv["total_mb"])
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write("nous=%d\n" % nous)


if __name__ == "__main__":
    if not BASE.strip("/"):
        sys.exit("Falta MEDIA_SERVER_BASE")
    arxiva(os.environ.get("FONOTECA_SORTIDA", "fono/f"), os.environ.get("FONOTECA_REGISTRE", ""),
           int(os.environ.get("FONOTECA_MAX_MINUTS", "300")), int(os.environ.get("FONOTECA_KBPS", "48")))
