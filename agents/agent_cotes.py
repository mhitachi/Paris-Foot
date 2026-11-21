"""AGENT Cotes — The Odds API (gratuit, 500 crédits/mois).
Relevé du matin : 1/N/2 + plus/moins 2.5 buts pour les championnats qui jouent dans les 3 jours.
Relevé du soir : 1/N/2 seulement, pour les matchs des prochaines 30 h (sert aux mouvements de cotes
et à la cote de clôture). On n'appelle que les championnats qui ont des matchs : ça tient dans le gratuit."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

import config
from agents.base_donnees import dt, etat, maintenant
from agents.noms import similarite

URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
NOM = "Cotes"


def trouver_match(con, ligue, dom, ext, debut):
    lo = (debut - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (debut + timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
    meilleur, smax = None, 0.0
    for c in con.execute("SELECT id, equipe_dom, equipe_ext FROM matchs WHERE ligue=? AND date_utc BETWEEN ? AND ?",
                         (ligue, lo, hi)).fetchall():
        s = (similarite(c["equipe_dom"], dom) + similarite(c["equipe_ext"], ext)) / 2
        if s > smax:
            meilleur, smax = c, s
    return meilleur if smax >= 0.6 else None


def enregistrer_snapshot(con, match_id, ts):
    """Résumé de toutes les cotes d'un match à cet instant (pour l'historique)."""
    par = defaultdict(list)
    pin = {}
    for r in con.execute("SELECT bookmaker, marche, issue, cote FROM cotes WHERE match_id=?", (match_id,)):
        par[(r["marche"], r["issue"])].append(r["cote"])
        if r["bookmaker"] == "pinnacle":
            pin[(r["marche"], r["issue"])] = r["cote"]
    for (marche, issue), cs in par.items():
        con.execute("INSERT OR REPLACE INTO cotes_historique VALUES (?,?,?,?,?,?,?)",
                    (match_id, marche, issue, sum(cs) / len(cs), max(cs), pin.get((marche, issue)), ts))


def executer(con, log):
    if not config.ODDS_API_KEY:
        etat(con, NOM, "inactif", "Clé The Odds API manquante")
        return
    now = datetime.now(timezone.utc)
    soir = config.MODE == "soir"
    horizon = now + (timedelta(hours=30) if soir else timedelta(days=3))
    marches = "h2h" if soir else "h2h,totals"
    ts = maintenant()
    nb, perdus, restant, erreurs = 0, 0, "?", []
    for code, info in config.LIGUES.items():
        a_venir = con.execute("SELECT COUNT(*) FROM matchs WHERE ligue=? AND statut IN ('SCHEDULED','TIMED') "
                              "AND date_utc BETWEEN ? AND ?", (code, now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                                horizon.strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchone()[0]
        if not a_venir:
            continue  # pas de match -> on économise les crédits
        r = requests.get(URL.format(sport=info["odds"]), timeout=30, params={
            "apiKey": config.ODDS_API_KEY, "regions": "eu,uk", "markets": marches, "oddsFormat": "decimal"})
        restant = r.headers.get("x-requests-remaining", restant)
        if r.status_code != 200:
            erreurs.append(f"{code}: {r.status_code}")
            continue
        for ev in r.json():
            m = trouver_match(con, code, ev["home_team"], ev["away_team"], dt(ev["commence_time"]))
            if not m:
                perdus += 1
                continue
            nb += 1
            for bk in ev.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    for o in mk.get("outcomes", []):
                        if mk["key"] == "h2h":
                            marche = "1X2"
                            issue = "N" if o["name"] == "Draw" else "1" if o["name"] == ev["home_team"] else "2"
                        elif mk["key"] == "totals" and float(o.get("point", 0)) == 2.5:
                            marche, issue = "OU25", ("+2.5" if o["name"] == "Over" else "-2.5")
                        else:
                            continue
                        con.execute("INSERT OR REPLACE INTO cotes VALUES (?,?,?,?,?,?)",
                                    (m["id"], bk["key"], marche, issue, float(o["price"]), ts))
            enregistrer_snapshot(con, m["id"], ts)
    con.commit()
    log(f"  cotes pour {nb} matchs ({perdus} non reconnus) — crédits restants : {restant}")
    etat(con, NOM, "erreur" if erreurs and not nb else "ok",
         f"Relevé du {'soir' if soir else 'matin'} : {nb} matchs. Crédits gratuits restants ce mois : {restant}"
         + (f" (problèmes : {', '.join(erreurs)})" if erreurs else ""))
