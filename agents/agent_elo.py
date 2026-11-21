"""AGENT Classement Elo — ClubElo (gratuit, sans clé).
1) La note Elo de chaque club (force globale, mise à jour après chaque match).
2) Les probabilités 1/N/2 que ClubElo calcule pour les matchs à venir."""
import csv
import io
import time
from datetime import datetime, timedelta, timezone

import requests

import config
from agents.base_donnees import etat, maintenant
from agents.noms import similarite

NOM = "Elo"


def lire_csv(url):
    """3 essais espacés : le site ClubElo est parfois surchargé (erreur 502)."""
    for essai in range(3):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return list(csv.DictReader(io.StringIO(r.text)))
        except requests.RequestException:
            if essai == 2:
                raise
            time.sleep(20)


def executer(con, log):
    now = datetime.now(timezone.utc)
    pays_vers_ligue = {i["pays"]: c for c, i in config.LIGUES.items()}
    # 1) notes
    notes = lire_csv(f"http://api.clubelo.com/{now:%Y-%m-%d}")
    equipes = {c: [r[0] for r in con.execute(
        "SELECT DISTINCT equipe_dom FROM matchs WHERE ligue=? AND saison>=?", (c, now.year - 1))]
        for c in config.LIGUES}
    nb_notes = 0
    for row in notes:
        lig = pays_vers_ligue.get(row.get("Country"))
        if not lig or row.get("Level") != "1":
            continue
        best = max(equipes[lig], key=lambda e: similarite(e, row["Club"]), default=None)
        if best and similarite(best, row["Club"]) >= 0.6:
            con.execute("INSERT OR REPLACE INTO elo_notes VALUES (?,?,?,?)",
                        (lig, best, float(row["Elo"]), maintenant()))
            nb_notes += 1
    # 2) probabilités des matchs à venir
    nb_p = 0
    for row in lire_csv("http://api.clubelo.com/Fixtures"):
        lig = pays_vers_ligue.get(row.get("Country"))
        if not lig:
            continue
        p1 = pn = p2 = 0.0
        for k, v in row.items():
            if not k or not k.startswith("GD"):
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if k in ("GD=0",):
                pn += v
            elif k.startswith("GD<") or k.startswith("GD=-"):
                p2 += v
            else:
                p1 += v
        tot = p1 + pn + p2
        if tot <= 0:
            continue
        d = datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        lo, hi = (d - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), (d + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cands = con.execute("SELECT id, equipe_dom, equipe_ext FROM matchs WHERE ligue=? AND date_utc BETWEEN ? AND ?",
                            (lig, lo, hi)).fetchall()
        best = max(cands, key=lambda c: similarite(c[1], row["Home"]) + similarite(c[2], row["Away"]), default=None)
        if best and (similarite(best[1], row["Home"]) + similarite(best[2], row["Away"])) / 2 >= 0.6:
            con.execute("INSERT OR REPLACE INTO elo_probas VALUES (?,?,?,?,?)",
                        (best[0], p1 / tot, pn / tot, p2 / tot, maintenant()))
            nb_p += 1
    con.commit()
    log(f"  {nb_notes} notes Elo, {nb_p} matchs avec probabilités Elo")
    etat(con, NOM, "ok" if nb_p else "erreur", f"{nb_notes} clubs notés, {nb_p} matchs analysés")
