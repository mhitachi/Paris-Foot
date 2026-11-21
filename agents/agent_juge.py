"""AGENT Juge + Détecteur de pièges + Mouvements de cotes.
Le juge écoute les 4 analystes (marché, buts, xG, Elo), les pondère et rend une probabilité finale.
Le détecteur de pièges signale tout ce qui rend l'analyse fragile.
L'agent mouvements repère les cotes qui chutent (souvent le signe d'une info qui circule)."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

import config
from agents import agent_contexte
from agents.base_donnees import etat, maintenant

ISSUES = ["1", "N", "2"]


def proba_marche(con, match_id, marche="1X2"):
    issues = ISSUES if marche == "1X2" else ["+2.5", "-2.5"]
    par_bk = defaultdict(dict)
    for r in con.execute("SELECT bookmaker, issue, cote FROM cotes WHERE match_id=? AND marche=?", (match_id, marche)):
        par_bk[r["bookmaker"]][r["issue"]] = r["cote"]
    bks = [c for c in par_bk.values() if all(i in c for i in issues)]
    if len(bks) < 3:
        return None, None
    brut = {i: sum(1 / c[i] for c in bks) / len(bks) for i in issues}
    tot = sum(brut.values())
    meilleures = {i: max(c[i] for c in bks) for i in issues}
    return {i: brut[i] / tot for i in issues}, meilleures


def mouvements(con, match_id):
    """Compare la première et la dernière photo des cotes 1/N/2."""
    out = []
    for i in ISSUES:
        rows = con.execute("SELECT moyenne FROM cotes_historique WHERE match_id=? AND marche='1X2' AND issue=? "
                           "ORDER BY ts", (match_id, i)).fetchall()
        if len(rows) >= 2:
            de, a = rows[0][0], rows[-1][0]
            out.append({"issue": i, "de": round(de, 2), "a": round(a, 2), "variation": round(a / de - 1, 3)})
    return out


def ajuster_matrice(M, p):
    """Recale la grille des scores pour qu'elle colle aux probabilités 1/N/2 du juge."""
    M = np.array(M)
    X, Y = np.indices(M.shape)
    zones = {"1": X > Y, "N": X == Y, "2": X < Y}
    for i, z in zones.items():
        s = M[z].sum()
        if s > 0:
            M[z] *= p[i] / s
    return M / M.sum()


def executer(con, log):
    now = datetime.now(timezone.utc)
    now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    lim = (now + timedelta(days=config.JOURS_A_VENIR)).strftime("%Y-%m-%dT%H:%M:%SZ")
    matchs = con.execute("""SELECT * FROM matchs WHERE statut IN ('SCHEDULED','TIMED') AND date_utc BETWEEN ? AND ?
                            AND ligue IN (%s)""" % ",".join("?" * len(config.LIGUES)),
                         (now_s, lim, *config.LIGUES)).fetchall()
    tables = {c: agent_contexte.classement(con, c, max([r[0] for r in con.execute(
        "SELECT saison FROM matchs WHERE ligue=?", (c,))] or [0])) for c in config.LIGUES}
    nb, nb_alertes = 0, 0
    for m in matchs:
        preds = {r["modele"]: r for r in con.execute("SELECT * FROM predictions WHERE match_id=?", (m["id"],))}
        if "buts" not in preds:
            continue
        modeles = {"buts": {i: preds["buts"][k] for i, k in zip(ISSUES, ("p_dom", "p_nul", "p_ext"))}}
        if "xg" in preds:
            modeles["xg"] = {i: preds["xg"][k] for i, k in zip(ISSUES, ("p_dom", "p_nul", "p_ext"))}
        elo = con.execute("SELECT p1, pn, p2 FROM elo_probas WHERE match_id=?", (m["id"],)).fetchone()
        if elo:
            modeles["elo"] = dict(zip(ISSUES, elo))
        pm, _ = proba_marche(con, m["id"])
        if pm:
            modeles["marche"] = pm
        poids = {k: config.POIDS[k] for k in modeles}
        tot = sum(poids.values())
        p = {i: sum(poids[k] * modeles[k][i] for k in modeles) / tot for i in ISSUES}

        # plus/moins 2.5 : moitié modèles (buts/xG), moitié marché
        p_over_mod = np.mean([preds[k]["p_over25"] for k in ("buts", "xg") if k in preds])
        pmo, _ = proba_marche(con, m["id"], "OU25")
        p_over = 0.5 * p_over_mod + 0.5 * pmo["+2.5"] if pmo else p_over_mod

        # pièges
        ctx = agent_contexte.contexte_match(con, m, tables)
        pieges = []
        for cote, nom in (("dom", m["equipe_dom"]), ("ext", m["equipe_ext"])):
            c = ctx[cote]
            if c["promu"]:
                pieges.append(f"{nom} vient d'être promu : peu de données fiables sur cette équipe.")
            if c["joues"] < 8:
                pieges.append(f"{nom} n'a joué que {c['joues']} matchs cette saison : début de saison, prudence.")
            f = c["fatigue"]
            if f["repos"] is not None and f["repos"] <= 3:
                pieges.append(f"{nom} n'a eu que {f['repos']} jours de repos : risque de fatigue ou de rotation.")
            if f["europe"]:
                pieges.append(f"{nom} a joué en Ligue des champions cette semaine.")
            if c["enjeu"] == "Plus rien à jouer":
                pieges.append(f"{nom} n'a plus rien à jouer : motivation incertaine.")
        ecart = max(abs(modeles["marche"][i] - p[i]) for i in ISSUES) if pm else 0
        desaccord = max(abs(modeles[a][i] - modeles[b][i]) for a in modeles for b in modeles for i in ISSUES)
        if pm and max(abs(modeles["buts"][i] - pm[i]) for i in ISSUES) > 0.12:
            pieges.append("Gros désaccord entre nos modèles et les bookmakers : ils savent peut-être quelque chose "
                          "(blessure, rotation). Lis la presse avant de parier.")
        mv = mouvements(con, m["id"])
        for x in mv:
            if x["variation"] <= -config.BAISSE_ALERTE:
                nb_alertes += 1
        confiance = ("faible" if len(pieges) >= 2 or desaccord > 0.15 else
                     "forte" if not pieges and desaccord < 0.08 and len(modeles) >= 3 else "moyenne")
        M = ajuster_matrice(json.loads(preds["buts"]["matrice"]), p)
        con.execute("INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m["id"], p["1"], p["N"], p["2"], float(p_over), json.dumps(modeles), json.dumps(pieges),
                     confiance, json.dumps([[round(float(v), 5) for v in l] for l in M]), maintenant()))
        nb += 1
    con.commit()
    log(f"  {nb} matchs jugés, {nb_alertes} alertes de cotes")
    etat(con, "Juge", "ok" if nb else "inactif", f"{nb} matchs analysés par les 4 analystes")
    etat(con, "Détecteur de pièges", "ok", "Promus, début de saison, fatigue, désaccords, matchs sans enjeu")
    etat(con, "Mouvements de cotes", "ok", f"{nb_alertes} chutes de cote repérées")
