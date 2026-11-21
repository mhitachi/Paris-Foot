"""AGENT Suivi + Cote de clôture.
Règle les paris test du robot, relève la dernière cote avant le coup d'envoi
et mesure si le robot "bat la cote de clôture"."""
from agents.base_donnees import etat, maintenant


def gagnant(marche, issue, bd, be):
    if marche == "1X2":
        return issue == ("1" if bd > be else "2" if be > bd else "N")
    return (bd + be >= 3) == (issue == "+2.5")


def cote_cloture(con, match_id, marche, issue, date_match):
    """Meilleure cote du dernier relevé avant le coup d'envoi (comparaison juste avec la cote prise)."""
    r = con.execute("""SELECT meilleure FROM cotes_historique WHERE match_id=? AND marche=? AND issue=? AND ts<=?
                       ORDER BY ts DESC LIMIT 1""", (match_id, marche, issue, date_match)).fetchone()
    return r[0] if r else None


def executer(con, log):
    rows = con.execute("""SELECT p.*, m.buts_dom, m.buts_ext, m.date_utc, m.statut st FROM paris p
                          JOIN matchs m ON m.id=p.match_id WHERE p.statut='en attente'""").fetchall()
    regles = 0
    for p in rows:
        if p["cote_cloture"] is None and p["date_utc"] <= maintenant():
            cc = cote_cloture(con, p["match_id"], p["marche"], p["issue"], p["date_utc"])
            if cc:
                con.execute("UPDATE paris SET cote_cloture=? WHERE id=?", (cc, p["id"]))
        if p["st"] == "FINISHED" and p["buts_dom"] is not None:
            ok = gagnant(p["marche"], p["issue"], p["buts_dom"], p["buts_ext"])
            con.execute("UPDATE paris SET statut=?, gain=? WHERE id=?",
                        ("gagné" if ok else "perdu", round(p["mise"] * (p["cote"] - 1), 2) if ok else -p["mise"], p["id"]))
            regles += 1
        elif p["st"] in ("CANCELLED", "POSTPONED", "SUSPENDED"):
            con.execute("UPDATE paris SET statut='annulé', gain=0 WHERE id=?", (p["id"],))
    con.commit()
    b = bilan(con)
    log(f"  {regles} paris réglés — {b['nb']} au total, rendement {b['roi']:+.1%}")
    etat(con, "Suivi", "ok", f"{b['nb']} paris test réglés, rendement {b['roi']:+.1%}")
    etat(con, "Cote de clôture", "ok",
         f"Le robot a battu la cote de clôture {b['clv_battu']} fois sur {b['clv_nb']}" if b["clv_nb"] else
         "Pas encore de pari terminé à mesurer")


def bilan(con):
    r = con.execute("""SELECT COUNT(*) nb, COALESCE(SUM(statut='gagné'),0) g, COALESCE(SUM(mise),0) mises,
                       COALESCE(SUM(gain),0) gains FROM paris WHERE statut IN ('gagné','perdu')""").fetchone()
    clv = con.execute("SELECT cote, cote_cloture FROM paris WHERE cote_cloture IS NOT NULL "
                      "AND statut IN ('gagné','perdu')").fetchall()
    battu = sum(1 for c in clv if c["cote"] > c["cote_cloture"])
    return {"nb": r["nb"], "gagnes": r["g"], "profit": round(r["gains"], 2),
            "roi": (r["gains"] / r["mises"]) if r["mises"] else 0.0,
            "clv_nb": len(clv), "clv_battu": battu,
            "clv_moyen": (sum(c["cote"] / c["cote_cloture"] - 1 for c in clv) / len(clv)) if clv else None}
