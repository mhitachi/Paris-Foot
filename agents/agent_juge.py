"""AGENT Juge + Détecteur de pièges + Mouvements de cotes.
Le juge fixe le VRAI PRIX de chaque pari à partir des cotes de Pinnacle, marge retirée
(à défaut : la moyenne des bookmakers). Les analystes (buts, xG, Elo) restent affichés pour information.
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


def proba_pinnacle(con, match_id, marche="1X2"):
    issues = ISSUES if marche == "1X2" else ["+2.5", "-2.5"]
    c = {r["issue"]: r["cote"] for r in con.execute(
        "SELECT issue, cote FROM cotes WHERE match_id=? AND marche=? AND bookmaker='pinnacle'", (match_id, marche))}
    if not all(i in c for i in issues):
        return None
    inv = {i: 1 / c[i] for i in issues}
    t = sum(inv.values())
    return {i: inv[i] / t for i in issues}


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


def ajuster_matrice(M, p, p_over=None):
    """Recale la grille des scores pour qu'elle colle au vrai prix (1/N/2 et plus/moins 2.5 buts).
    Ainsi les autres paris (double chance, les deux marquent, handicap...) héritent du prix du marché."""
    M = np.array(M, dtype=float)
    M /= M.sum()
    X, Y = np.indices(M.shape)
    zones = [(X > Y, p["1"]), (X == Y, p["N"]), (X < Y, p["2"])]
    if p_over is not None:
        zones2 = [(X + Y >= 3, p_over), (X + Y < 3, 1 - p_over)]
    for _ in range(30 if p_over is not None else 1):
        for z, cible in zones + (zones2 if p_over is not None else []):
            s = M[z].sum()
            if s > 0:
                M[z] *= cible / s
            M /= M.sum()
    return M


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
        pin = proba_pinnacle(con, m["id"])
        if pin:
            modeles["pinnacle"] = pin
        if pin:                      # 1) Pinnacle = le vrai prix
            p = dict(pin)
        elif pm:                     # 2) sinon la moyenne des bookmakers
            p = dict(pm)
        else:                        # 3) en dernier recours, nos modèles
            poids = {k: config.POIDS[k] for k in modeles if k in config.POIDS}
            tot = sum(poids.values())
            p = {i: sum(poids[k] * modeles[k][i] for k in poids) / tot for i in ISSUES}

        pino = proba_pinnacle(con, m["id"], "OU25")
        pmo, _ = proba_marche(con, m["id"], "OU25")
        p_over_mod = np.mean([preds[k]["p_over25"] for k in ("buts", "xg") if k in preds])
        p_over = pino["+2.5"] if pino else pmo["+2.5"] if pmo else p_over_mod

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
        desaccord = max(abs(modeles[a][i] - modeles[b][i]) for a in modeles for b in modeles for i in ISSUES)
        ref = pin or pm
        if ref and max(abs(modeles["buts"][i] - ref[i]) for i in ISSUES) > 0.15:
            pieges.append("Gros écart entre les statistiques et le prix des bookmakers : ils savent sûrement quelque chose "
                          "(blessure, rotation, changement d'entraîneur). Lis la presse avant de parier.")
        mv = mouvements(con, m["id"])
        for x in mv:
            if x["variation"] <= -config.BAISSE_ALERTE:
                nb_alertes += 1
        confiance = ("faible" if len(pieges) >= 2 or not (pin or pm) else
                     "forte" if not pieges and pin and desaccord < 0.12 else "moyenne")
        M = ajuster_matrice(json.loads(preds["buts"]["matrice"]), p, float(p_over))
        con.execute("INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m["id"], p["1"], p["N"], p["2"], float(p_over), json.dumps(modeles), json.dumps(pieges),
                     confiance, json.dumps([[round(float(v), 5) for v in l] for l in M]), maintenant()))
        nb += 1
    con.commit()
    log(f"  {nb} matchs jugés, {nb_alertes} alertes de cotes")
    nb_pin = con.execute("SELECT COUNT(*) FROM verdicts WHERE modeles LIKE '%pinnacle%' AND maj>=?",
                         ((now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()[0]
    etat(con, "Juge", "ok" if nb else "inactif", f"{nb} matchs avec un vrai prix ({nb_pin} grâce à Pinnacle)")
    etat(con, "Détecteur de pièges", "ok", "Promus, début de saison, fatigue, désaccords, matchs sans enjeu")
    etat(con, "Mouvements de cotes", "ok", f"{nb_alertes} chutes de cote repérées")
