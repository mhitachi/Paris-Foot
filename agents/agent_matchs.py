"""AGENT Calendrier & résultats — football-data.org (gratuit).
Récupère la saison en cours et la précédente des 6 championnats, plus la Ligue des champions
(utile pour mesurer la fatigue des équipes qui jouent en semaine)."""
import time

import requests

import config
from agents.base_donnees import etat, maintenant, saison_en_cours

URL = "https://api.football-data.org/v4/competitions/{code}/matches"
NOM = "Calendrier"


def executer(con, log):
    if not config.FOOTBALL_DATA_KEY:
        etat(con, NOM, "inactif", "Clé football-data manquante")
        return
    s = saison_en_cours()
    total, erreurs = 0, []
    for code in list(config.LIGUES) + ["CL"]:
        for saison in ((s,) if code == "CL" else (s - 1, s)):
            if saison < s and con.execute(
                    "SELECT COUNT(*) FROM matchs WHERE ligue=? AND saison=? AND statut='FINISHED'",
                    (code, saison)).fetchone()[0] > 250:
                continue  # saison passée déjà complète
            r = requests.get(URL.format(code=code), headers={"X-Auth-Token": config.FOOTBALL_DATA_KEY},
                             params={"season": saison}, timeout=30)
            time.sleep(6.5)  # limite gratuite : 10 appels / minute
            if r.status_code != 200:
                erreurs.append(f"{code} {saison}: {r.status_code}")
                continue
            for m in r.json().get("matches", []):
                ft = (m.get("score") or {}).get("fullTime") or {}
                con.execute("""INSERT INTO matchs VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET date_utc=excluded.date_utc, statut=excluded.statut,
                    buts_dom=excluded.buts_dom, buts_ext=excluded.buts_ext, maj=excluded.maj""",
                    (m["id"], code, saison, m.get("matchday"), m["utcDate"], m["status"],
                     m["homeTeam"]["name"], m["awayTeam"]["name"], ft.get("home"), ft.get("away"), maintenant()))
                total += 1
    con.commit()
    log(f"  {total} matchs mis à jour {erreurs or ''}")
    etat(con, NOM, "erreur" if erreurs and not total else "ok",
         f"{total} matchs à jour" + (f" (problèmes : {', '.join(erreurs)})" if erreurs else ""))
