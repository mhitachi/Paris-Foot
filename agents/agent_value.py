"""AGENT Conseils (+ paris test du robot).
Un conseil apparaît quand le juge voit une issue plus probable que ce que paie la meilleure cote du marché.
Le robot joue chaque conseil avec 10 CHF virtuels : c'est sa façon de prouver (ou non) qu'il est bon."""
from datetime import datetime, timezone

import config
from agents.agent_juge import proba_marche
from agents.base_donnees import etat, maintenant


def opportunites(con, v):
    """Toutes les issues 1/N/2 et +/-2.5 d'un match, avec avantage par rapport à la meilleure cote."""
    out = []
    _, best = proba_marche(con, v["match_id"])
    if best:
        for i, p in (("1", v["p1"]), ("N", v["pn"]), ("2", v["p2"])):
            out.append({"marche": "1X2", "issue": i, "proba": p, "cote": best[i], "avantage": p * best[i] - 1})
    _, best = proba_marche(con, v["match_id"], "OU25")
    if best:
        for i, p in (("+2.5", v["p_over25"]), ("-2.5", 1 - v["p_over25"])):
            out.append({"marche": "OU25", "issue": i, "proba": p, "cote": best[i], "avantage": p * best[i] - 1})
    return out


def conseil(con, v):
    if v["confiance"] == "faible":
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
    etat(con, "Conseils", "ok", f"{total} belles occasions repérées sur les 7 prochains jours")
