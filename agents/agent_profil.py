"""AGENT Profil de jeu — football-data.co.uk (gratuit).
Tirs, tirs cadrés, corners, cartons, fautes de chaque match de la saison
(+ l'arbitre pour la Premier League)."""
import csv
import io
from datetime import datetime

import requests

import config
from agents.base_donnees import etat, saison_en_cours

NOM = "Profil de jeu"


def url_saison(code, saison):
    return f"https://www.football-data.co.uk/mmz4281/{saison % 100:02d}{(saison + 1) % 100:02d}/{code}.csv"


def lire(code, saison):
    r = requests.get(url_saison(code, saison), timeout=30)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", errors="ignore"))))


def entier(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def date_iso(s):
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def executer(con, log):
    s = saison_en_cours()
    total, erreurs = 0, []
    for code, info in config.LIGUES.items():
        try:
            lignes = lire(info["fdcouk"], s)
        except Exception as ex:
            erreurs.append(f"{code}: {type(ex).__name__}")
            continue
        for r in lignes:
            d = date_iso(r.get("Date", ""))
            if not d or not r.get("HomeTeam"):
                continue
            con.execute("INSERT OR REPLACE INTO profil_matchs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (code, d, r["HomeTeam"], r["AwayTeam"], entier(r.get("FTHG")), entier(r.get("FTAG")),
                         entier(r.get("HS")), entier(r.get("AS")), entier(r.get("HST")), entier(r.get("AST")),
                         entier(r.get("HC")), entier(r.get("AC")), entier(r.get("HY")), entier(r.get("AY")),
                         entier(r.get("HR")), entier(r.get("AR")), entier(r.get("HF")), entier(r.get("AF")),
                         r.get("Referee") or None))
            total += 1
    con.commit()
    log(f"  {total} matchs avec statistiques de jeu {erreurs or ''}")
    etat(con, NOM, "ok" if total else "erreur",
         f"{total} matchs analysés" + (f" (problèmes : {', '.join(erreurs)})" if erreurs else ""))
