"""AGENTS de contexte (calculs, 0 appel Internet) :
- Forme : 6 derniers matchs, séparément à domicile et à l'extérieur
- Fatigue : jours de repos, matchs en 21 jours, Ligue des champions en semaine
- Classement & enjeu : titre, Europe, maintien, match sans enjeu
- Profil de jeu : tirs, corners, cartons moyens (données football-data.co.uk)
"""
from datetime import timedelta

import config
from agents.base_donnees import dt, etat
from agents.noms import similarite


def classement(con, ligue, saison):
    pts = {}
    for r in con.execute("""SELECT equipe_dom d, equipe_ext e, buts_dom bd, buts_ext be FROM matchs
                            WHERE ligue=? AND saison=? AND statut='FINISHED' AND buts_dom IS NOT NULL""",
                         (ligue, saison)):
        for eq, bp, bc in ((r["d"], r["bd"], r["be"]), (r["e"], r["be"], r["bd"])):
            t = pts.setdefault(eq, {"equipe": eq, "pts": 0, "j": 0, "diff": 0})
            t["j"] += 1
            t["diff"] += bp - bc
            t["pts"] += 3 if bp > bc else 1 if bp == bc else 0
    tab = sorted(pts.values(), key=lambda t: (-t["pts"], -t["diff"]))
    for i, t in enumerate(tab):
        t["rang"] = i + 1
    return tab


def enjeu(tab, equipe, info, nb_journees):
    t = next((x for x in tab if x["equipe"] == equipe), None)
    if not t or not tab:
        return None, None
    n = len(tab)
    restants = max(nb_journees - t["j"], 0)
    pts_max = 3 * restants
    premier = tab[0]["pts"]
    europe = tab[min(info["europe"], n) - 1]["pts"]
    maintien = tab[n - info["relegues"] - 1]["pts"] if n > info["relegues"] else 0
    if t["rang"] <= 2 or premier - t["pts"] <= 6:
        txt = "Course au titre"
    elif t["rang"] > n - info["relegues"] or t["pts"] - maintien <= 4:
        txt = "Lutte pour le maintien"
    elif abs(t["pts"] - europe) <= 5:
        txt = "Course à l'Europe"
    else:
        txt = "Milieu de tableau"
    # fin de saison : plus rien à jouer ?
    if restants <= 8 and premier - t["pts"] > pts_max and europe - t["pts"] > pts_max and t["pts"] - maintien > pts_max:
        txt = "Plus rien à jouer"
    return t, txt


def forme(con, ligue, equipe, avant, lieu):
    col = "equipe_dom" if lieu == "dom" else "equipe_ext"
    rows = con.execute(f"""SELECT equipe_dom, equipe_ext, buts_dom, buts_ext FROM matchs
                           WHERE ligue=? AND {col}=? AND statut='FINISHED' AND date_utc<? AND buts_dom IS NOT NULL
                           ORDER BY date_utc DESC LIMIT 6""", (ligue, equipe, avant)).fetchall()
    serie, pts = "", 0
    for r in rows:
        bp, bc = (r[2], r[3]) if lieu == "dom" else (r[3], r[2])
        serie += "V" if bp > bc else "N" if bp == bc else "D"
        pts += 3 if bp > bc else 1 if bp == bc else 0
    return serie[::-1], (pts / (3 * len(rows)) if rows else None)


def fatigue(con, equipe, date):
    d = dt(date)
    rows = con.execute("""SELECT date_utc, ligue FROM matchs WHERE (equipe_dom=? OR equipe_ext=?) AND date_utc<?
                          AND date_utc>? ORDER BY date_utc DESC""",
                       (equipe, equipe, date, (d - timedelta(days=21)).strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchall()
    repos = (d - dt(rows[0]["date_utc"])).days if rows else None
    europe = any(r["ligue"] == "CL" and (d - dt(r["date_utc"])).days <= 5 for r in rows)
    return {"repos": repos, "matchs_21j": len(rows), "europe": europe}


def profil(con, ligue, equipe):
    noms = [r[0] for r in con.execute("SELECT DISTINCT equipe_dom FROM profil_matchs WHERE ligue=?", (ligue,))]
    if not noms:
        return None
    nom = max(noms, key=lambda n: similarite(n, equipe))
    if similarite(nom, equipe) < 0.6:
        return None
    rows = con.execute("SELECT * FROM profil_matchs WHERE ligue=? AND (equipe_dom=? OR equipe_ext=?)",
                       (ligue, nom, nom)).fetchall()
    if not rows:
        return None
    acc = {"buts_pour": [], "buts_contre": [], "tirs": [], "cadres": [], "corners": [], "cartons": []}
    for r in rows:
        d = r["equipe_dom"] == nom
        vals = {"buts_pour": r["bd"] if d else r["be"], "buts_contre": r["be"] if d else r["bd"],
                "tirs": r["tirs_d"] if d else r["tirs_e"], "cadres": r["cadres_d"] if d else r["cadres_e"],
                "corners": r["corners_d"] if d else r["corners_e"],
                "cartons": ((r["jaunes_d"] or 0) + 2 * (r["rouges_d"] or 0)) if d else
                           ((r["jaunes_e"] or 0) + 2 * (r["rouges_e"] or 0))}
        for k, v in vals.items():
            if v is not None:
                acc[k].append(v)
    return {k: round(sum(v) / len(v), 1) for k, v in acc.items() if v} | {"matchs": len(rows)}


def arbitre_stats(con, nom):
    """Moyennes d'un arbitre (Premier League uniquement en gratuit)."""
    if not nom:
        return None
    rows = con.execute("SELECT * FROM profil_matchs WHERE arbitre=?", (nom,)).fetchall()
    if len(rows) < 3:
        return None
    cartons = [(r["jaunes_d"] or 0) + (r["jaunes_e"] or 0) for r in rows]
    fautes = [(r["fautes_d"] or 0) + (r["fautes_e"] or 0) for r in rows]
    return {"matchs": len(rows), "jaunes": round(sum(cartons) / len(rows), 1), "fautes": round(sum(fautes) / len(rows), 1)}


def contexte_match(con, m, tables):
    info = config.LIGUES[m["ligue"]]
    tab = tables[m["ligue"]]
    nb_j = 2 * (len(tab) - 1) if tab else 38
    out = {}
    for cote, eq in (("dom", m["equipe_dom"]), ("ext", m["equipe_ext"])):
        t, enj = enjeu(tab, eq, info, nb_j)
        serie, ratio = forme(con, m["ligue"], eq, m["date_utc"], cote)
        elo = con.execute("SELECT elo FROM elo_notes WHERE ligue=? AND equipe=?", (m["ligue"], eq)).fetchone()
        promu = not con.execute("SELECT 1 FROM matchs WHERE ligue=? AND saison=? AND (equipe_dom=? OR equipe_ext=?) LIMIT 1",
                                (m["ligue"], m["saison"] - 1, eq, eq)).fetchone()
        out[cote] = {"rang": t["rang"] if t else None, "points": t["pts"] if t else None,
                     "joues": t["j"] if t else 0, "enjeu": enj, "forme": serie,
                     "forme_ratio": ratio, "lieu": "à domicile" if cote == "dom" else "à l'extérieur",
                     "fatigue": fatigue(con, eq, m["date_utc"]), "elo": round(elo[0]) if elo else None,
                     "profil": profil(con, m["ligue"], eq), "promu": promu}
    return out


def executer(con, log):
    etat(con, "Forme", "ok", "Forme domicile / extérieur calculée sur les 6 derniers matchs")
    etat(con, "Fatigue", "ok", "Repos, matchs en 3 semaines, Ligue des champions")
    etat(con, "Enjeu", "ok", "Classements recalculés, enjeu de chaque équipe")
    log("  contexte prêt (calculé à la demande pour chaque match)")
