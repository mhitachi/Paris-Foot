"""AGENT xG (qualité des occasions) — Understat (gratuit, 5 grands championnats).
Récupère les "buts attendus" de chaque match joué. Pas disponible gratuitement pour l'Eredivisie."""
import json
import re

import requests

import config
from agents.base_donnees import etat, saison_en_cours

NOM = "xG"
ENTETES = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}


def recuperer(ligue, saison):
    # Méthode 1 : données intégrées à la page
    r = requests.get(f"https://understat.com/league/{ligue}/{saison}", headers=ENTETES, timeout=30)
    m = re.search(r"datesData\s*=\s*JSON\.parse\('(.*?)'\)", r.text)
    if m:
        return json.loads(m.group(1).encode("utf-8").decode("unicode_escape"))
    # Méthode 2 : point d'accès de données
    r = requests.get(f"https://understat.com/getLeagueData/{ligue}/{saison}", headers=ENTETES, timeout=30)
    r.raise_for_status()
    return r.json().get("dates", [])


def executer(con, log):
    s = saison_en_cours()
    total, erreurs = 0, []
    for code, info in config.LIGUES.items():
        if not info["understat"]:
            continue
        for saison in (s - 1, s):
            try:
                matchs = recuperer(info["understat"], saison)
            except Exception as ex:  # site indisponible ou modifié -> le juge fera sans
                erreurs.append(f"{code}: {type(ex).__name__}")
                continue
            for m in matchs:
                if not m.get("isResult"):
                    continue
                con.execute("INSERT OR REPLACE INTO xg_matchs VALUES (?,?,?,?,?,?)",
                            (code, m["datetime"].replace(" ", "T") + "Z", m["h"]["title"], m["a"]["title"],
                             float(m["xG"]["h"]), float(m["xG"]["a"])))
                total += 1
    con.commit()
    log(f"  {total} matchs avec xG {erreurs or ''}")
    etat(con, NOM, "ok" if total else "erreur",
         f"{total} matchs avec xG" + (f" (problèmes : {', '.join(erreurs)})" if erreurs else ""))
