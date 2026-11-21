"""
AGENT 4 — Modèle statistique (Dixon-Coles).
Pour chaque équipe, il estime une force d'attaque et une force de défense à partir
des scores passés (les matchs récents comptent plus), plus l'avantage du terrain.
Il en déduit la probabilité de chaque score exact, donc : 1/N/2, plus/moins 2.5, les deux marquent.
"""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

import config
from agents.base_donnees import dt, etat, maintenant
from agents.noms import similarite

MAX_BUTS = 10


def _tau(x, y, lh, la, rho):
    t = np.ones_like(lh)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


def ajuster(matchs, date_ref, rho_libre=True):
    """matchs : liste de (dom, ext, buts_dom, buts_ext, date datetime)."""
    equipes = sorted({m[0] for m in matchs} | {m[1] for m in matchs})
    idx = {e: i for i, e in enumerate(equipes)}
    n = len(equipes)
    h = np.array([idx[m[0]] for m in matchs])
    a = np.array([idx[m[1]] for m in matchs])
    x = np.array([m[2] for m in matchs], dtype=float)
    y = np.array([m[3] for m in matchs], dtype=float)
    jours = np.array([(date_ref - m[4]).days for m in matchs], dtype=float)
    w = np.exp(-config.DECAY_XI * np.clip(jours, 0, None))
    cst = gammaln(x + 1) + gammaln(y + 1)

    def nll(p):
        att = p[:n] - p[:n].mean()
        dfn = p[n:2 * n]
        dom, rho = p[2 * n], p[2 * n + 1]
        lh = np.exp(dom + att[h] + dfn[a])
        la = np.exp(att[a] + dfn[h])
        ll = (np.log(np.clip(_tau(x, y, lh, la, rho), 1e-10, None))
              + x * np.log(lh) - lh + y * np.log(la) - la - cst)
        reg = 0.01 * (np.sum(att ** 2) + np.sum(dfn ** 2))  # stabilise les équipes avec peu de matchs
        return -np.sum(w * ll) + reg

    p0 = np.concatenate([np.zeros(n), np.zeros(n), [0.25, -0.05 if rho_libre else 0.0]])
    bornes = [(-3, 3)] * (2 * n) + [(-1, 1), (-0.2, 0.2) if rho_libre else (0, 0)]
    res = minimize(nll, p0, method="L-BFGS-B", bounds=bornes)
    p = res.x
    att = p[:n] - p[:n].mean()
    return {"equipes": idx, "att": att, "def": p[n:2 * n], "dom": p[2 * n], "rho": p[2 * n + 1]}


def matrice_scores(mod, dom, ext):
    i, j = mod["equipes"][dom], mod["equipes"][ext]
    lh = float(np.exp(mod["dom"] + mod["att"][i] + mod["def"][j]))
    la = float(np.exp(mod["att"][j] + mod["def"][i]))
    k = np.arange(MAX_BUTS + 1)
    ph = np.exp(k * np.log(lh) - lh - gammaln(k + 1))
    pa = np.exp(k * np.log(la) - la - gammaln(k + 1))
    M = np.outer(ph, pa)
    r = mod["rho"]
    M[0, 0] *= 1 - lh * la * r
    M[0, 1] *= 1 + lh * r
    M[1, 0] *= 1 + la * r
    M[1, 1] *= 1 - r
    return M / M.sum(), lh, la


def probas(M):
    X, Y = np.indices(M.shape)
    return {
        "p_dom": float(M[X > Y].sum()), "p_nul": float(np.trace(M)), "p_ext": float(M[X < Y].sum()),
        "p_over25": float(M[X + Y >= 3].sum()), "p_under25": float(M[X + Y < 3].sum()),
        "p_btts": float(M[(X >= 1) & (Y >= 1)].sum()),
    }


MATRICE_TAILLE = 7  # scores de 0 à 6 transmis à l'application


def _predire_et_stocker(con, mod, modele, a_venir):
    nb = 0
    for m in a_venir:
        if m["equipe_dom"] not in mod["equipes"] or m["equipe_ext"] not in mod["equipes"]:
            continue
        M, lh, la = matrice_scores(mod, m["equipe_dom"], m["equipe_ext"])
        p = probas(M)
        petite = M[:MATRICE_TAILLE, :MATRICE_TAILLE]
        con.execute("INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (m["id"], modele, p["p_dom"], p["p_nul"], p["p_ext"], p["p_over25"], p["p_btts"],
                     lh, la, json.dumps([[round(float(v), 5) for v in ligne] for ligne in petite]), maintenant()))
        nb += 1
    return nb


def executer(con, log, maintenant_dt=None):
    """Deux analystes : le modèle sur les BUTS et le modèle sur les xG (qualité des occasions)."""
    now = maintenant_dt or datetime.now(timezone.utc)
    now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    limite = (now + timedelta(days=config.JOURS_A_VENIR)).strftime("%Y-%m-%dT%H:%M:%SZ")
    resume = []
    for code, info in config.LIGUES.items():
        a_venir = con.execute("""SELECT id, equipe_dom, equipe_ext FROM matchs WHERE ligue=?
                                 AND statut IN ('SCHEDULED','TIMED') AND date_utc BETWEEN ? AND ?""",
                              (code, now_s, limite)).fetchall()
        joues = con.execute("""SELECT equipe_dom, equipe_ext, buts_dom, buts_ext, date_utc FROM matchs
                               WHERE ligue=? AND statut='FINISHED' AND buts_dom IS NOT NULL""", (code,)).fetchall()
        if len(joues) >= config.MIN_MATCHS_LIGUE:
            mod = ajuster([(r[0], r[1], r[2], r[3], dt(r[4])) for r in joues], now)
            nb = _predire_et_stocker(con, mod, "buts", a_venir)
            resume.append(f"{info['nom']} {nb}")
            log(f"  {info['nom']} (buts) : {len(joues)} matchs, {nb} prédits")
        # modèle xG : on traduit les noms Understat vers nos noms
        xg = con.execute("SELECT equipe_dom, equipe_ext, xg_dom, xg_ext, date_utc FROM xg_matchs WHERE ligue=?",
                         (code,)).fetchall()
        if len(xg) >= config.MIN_MATCHS_LIGUE:
            noms = sorted({r[0] for r in joues} | {m["equipe_dom"] for m in a_venir} | {m["equipe_ext"] for m in a_venir})
            cache = {}

            def traduire(n):
                if n not in cache:
                    best = max(noms, key=lambda x: similarite(x, n), default=n)
                    cache[n] = best if similarite(best, n) >= 0.6 else n
                return cache[n]
            mod = ajuster([(traduire(r[0]), traduire(r[1]), r[2], r[3], dt(r[4])) for r in xg], now, rho_libre=False)
            nb = _predire_et_stocker(con, mod, "xg", a_venir)
            log(f"  {info['nom']} (xG) : {len(xg)} matchs, {nb} prédits")
    con.commit()
    etat(con, "Modèle buts", "ok" if resume else "erreur", "Matchs prédits : " + (", ".join(resume) or "aucun"))
    nb_xg = con.execute("SELECT COUNT(*) FROM predictions WHERE modele='xg' AND maj>=?",
                        ((now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()[0]
    etat(con, "Modèle xG", "ok" if nb_xg else "inactif", f"{nb_xg} matchs prédits (5 grands championnats)")
