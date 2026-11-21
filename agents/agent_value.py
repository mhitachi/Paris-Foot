"""AGENT Conseils (+ paris test du robot).
Un conseil apparaît quand un bookmaker classique paie nettement plus que le vrai prix de Pinnacle :
il est "en retard", et Jouez Sport l'est peut-être aussi.
Le robot joue chaque conseil avec 10 CHF virtuels : c'est sa façon de prouver (ou non) qu'il est bon."""
from datetime import datetime, timezone

import config
from agents.base_donnees import etat, maintenant


def meilleures_cotes(con, match_id, marche):
    """Meilleure cote par issue chez les bookmakers classiques (sans Pinnacle ni bourses d'échange)."""
    best = {}
    for r in con.execute("SELECT bookmaker, issue, cote FROM cotes WHERE match_id=? AND marche=?", (match_id, marche)):
        if r["bookmaker"] == "pinnacle" or r["bookmaker"].startswith(config.BOURSES):
            continue
        if r["cote"] > best.get(r["issue"], (0, ""))[0]:
            best[r["issue"]] = (r["cote"], r["bookmaker"])
    return best


def opportunites(con, v):
    """Toutes les issues 1/N/2 et +/-2.5 d'un match, avec avantage par rapport au vrai prix."""
    out = []
    best = {k: c for k, (c, _) in meilleures_cotes(con, v["match_id"], "1X2").items()}
    if len(best) == 3:
        for i, p in (("1", v["p1"]), ("N", v["pn"]), ("2", v["p2"])):
            out.append({"marche": "1X2", "issue": i, "proba": p, "cote": best[i], "avantage": p * best[i] - 1})
    best = {k: c for k, (c, _) in meilleures_cotes(con, v["match_id"], "OU25").items()}
    if len(best) == 2:
        for i, p in (("+2.5", v["p_over25"]), ("-2.5", 1 - v["p_over25"])):
            out.append({"marche": "OU25", "issue": i, "proba": p, "cote": best[i], "avantage": p * best[i] - 1})
    return out


def conseil(con, v):
    # pas de conseil sans le prix de Pinnacle (la référence), ni si l'analyse est fragile
    if v["confiance"] == "faible" or "pinnacle" not in (v["modeles"] or ""):
        return None
    ops = [o for o in opportunites(con, v)
           if o["avantage"] >= config.AVANTAGE_MIN and config.COTE_MIN <= o["cote"] <= config.COTE_MAX]
    return max(ops, key=lambda o: o["avantage"]) if ops else None


def executer(con, log):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute("""SELECT v.*, m.date_utc FROM verdicts v JOIN matchs m ON m.id=v.match_id
                          WHERE m.date_utc>? AND m.statut IN ('SCHEDULED','TIMED')""", (now,)).fetchall()
    par_jour = {}
    for v in rows:
        c = conseil(con, v)
        if c:
            c["match_id"] = v["match_id"]
            par_jour.setdefault(v["date_utc"][:10], []).append(c)
    nouveaux = 0
    for jour, liste in par_jour.items():
        for c in sorted(liste, key=lambda o: -o["avantage"])[:config.MAX_CONSEILS_JOUR]:
            cur = con.execute("INSERT OR IGNORE INTO paris (match_id, marche, issue, cote, proba, avantage, mise, cree) "
                              "VALUES (?,?,?,?,?,?,?,?)", (c["match_id"], c["marche"], c["issue"], c["cote"],
                                                           c["proba"], c["avantage"], config.MISE_ROBOT, maintenant()))
            nouveaux += cur.rowcount
    con.commit()
    total = sum(len(v) for v in par_jour.values())
    log(f"  {total} conseils, {nouveaux} nouveaux paris test")
    etat(con, "Conseils", "ok", f"{total} bookmakers en retard sur Pinnacle repérés (7 prochains jours)")
