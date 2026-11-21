"""Test sans Internet : fabrique deux faux championnats (équipes fictives avec une force cachée),
de fausses cotes, des xG, des notes Elo et des statistiques, puis fait tourner tous les agents de calcul.
Crée docs/data_demo.json (utilisé par la version de démonstration de l'application).
Usage : python test_simulation.py"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

DOSSIER = os.path.dirname(os.path.abspath(__file__))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "sim.db")
os.environ["DATA_JSON"] = os.path.join(DOSSIER, "docs", "data_demo.json")

import numpy as np  # noqa: E402
from scipy.stats import poisson  # noqa: E402

import config  # noqa: E402
from agents import (agent_contexte, agent_export, agent_juge, agent_modele, agent_suivi,  # noqa: E402
                    agent_testeur, agent_value)
from agents.base_donnees import connexion, etat, maintenant  # noqa: E402

rng = np.random.default_rng(11)
config.LIGUES = {k: config.LIGUES[k] for k in ("PL", "DED")}
EQUIPES = {
    "PL": ["Riverside FC", "Kingsbridge United", "Ashford Town", "Northgate City", "Harbour Athletic",
           "Westmoor Rovers", "Eastvale FC", "Stonebridge", "Millbrook Wanderers", "Oakfield United",
           "Redcliffe Albion", "Brookhaven", "Thornbury City", "Lakeside FC", "Highcroft Town",
           "Fairport United", "Elmstead Rovers", "Greywater FC", "Cranford Athletic", "Moorgate City"],
    "DED": ["FC Polder", "Vlietstad", "SC Duinwijk", "Haven '08", "Rietveld", "VV Molenaar", "Achterberg",
            "FC Kanaalzone", "Sluisdorp", "Heidegem", "Zandvoort-Oost", "Brugstad", "De Terp", "FC Waterland",
            "Kreekrak", "Lindenhof", "Nieuwdam", "Oranjepark"],
}
FORCE = {}
for lig, eqs in EQUIPES.items():
    att = rng.normal(0, 0.3, len(eqs)); att -= att.mean()
    FORCE[lig] = {e: (a, d) for e, a, d in zip(eqs, att, rng.normal(0, 0.25, len(eqs)))}


def lambdas(lig, d, e):
    return np.exp(0.25 + FORCE[lig][d][0] + FORCE[lig][e][1]), np.exp(FORCE[lig][e][0] + FORCE[lig][d][1])


con = connexion()
now = datetime.now(timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
mid = 1
avenir = []
for lig, eqs in EQUIPES.items():
    n = len(eqs)
    # saison passée complète + 13 journées de la saison en cours
    for saison, nb_j, debut in ((2025, 2 * (n - 1), now - timedelta(days=470)), (2026, 13, now - timedelta(days=95))):
        for j in range(nb_j):
            d0 = debut + timedelta(days=7 * j)
            ordre = rng.permutation(n)
            for k in range(n // 2):
                d, e = eqs[ordre[2 * k]], eqs[ordre[2 * k + 1]]
                lh, la = lambdas(lig, d, e)
                bd, be = int(rng.poisson(lh)), int(rng.poisson(la))
                date = d0 + timedelta(hours=int(rng.integers(0, 60)))
                con.execute("INSERT INTO matchs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (mid, lig, saison, j + 1, iso(date), "FINISHED", d, e, bd, be, maintenant()))
                con.execute("INSERT OR REPLACE INTO xg_matchs VALUES (?,?,?,?,?,?)",
                            (lig, iso(date), d, e, round(rng.gamma(4, lh / 4), 2), round(rng.gamma(4, la / 4), 2)))
                if saison == 2026:
                    sh, sa = int(rng.poisson(lh * 9)), int(rng.poisson(la * 9))
                    con.execute("INSERT OR REPLACE INTO profil_matchs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (lig, date.strftime("%Y-%m-%d"), d, e, bd, be, sh, sa, sh // 3, sa // 3,
                                 int(rng.poisson(5)), int(rng.poisson(4)), int(rng.poisson(1.8)), int(rng.poisson(2)),
                                 int(rng.random() < .05), int(rng.random() < .05), int(rng.poisson(11)), int(rng.poisson(11)),
                                 "M. Dean" if lig == "PL" else None))
                mid += 1
    # prochaine journée
    ordre = rng.permutation(n)
    for k in range(n // 2):
        d, e = eqs[ordre[2 * k]], eqs[ordre[2 * k + 1]]
        date = (now + timedelta(days=1 + k % 3)).replace(hour=[14, 17, 19][k % 3], minute=0, second=0)
        con.execute("INSERT INTO matchs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (mid, lig, 2026, 14, iso(date), "TIMED", d, e, None, None, maintenant()))
        lh, la = lambdas(lig, d, e)
        M = np.outer(poisson.pmf(np.arange(11), lh), poisson.pmf(np.arange(11), la))
        X, Y = np.indices(M.shape)
        vrai = {"1": M[X > Y].sum(), "N": np.trace(M), "2": M[X < Y].sum(), "+2.5": M[X + Y >= 3].sum(), "-2.5": M[X + Y < 3].sum()}
        for b, bk in enumerate(["pinnacle", "bet365", "unibet_eu", "betclic", "williamhill", "marathonbet"]):
            for marche, issues in (("1X2", ["1", "N", "2"]), ("OU25", ["+2.5", "-2.5"])):
                p = np.array([vrai[x] * np.exp(rng.normal(0, 0.07)) for x in issues])
                p = p / p.sum() * (1.025 if bk == "pinnacle" else 1.06)
                for x, q in zip(issues, p):
                    con.execute("INSERT INTO cotes VALUES (?,?,?,?,?,?)", (mid, bk, marche, x, round(1 / q, 2), maintenant()))
        # deux photos de cotes : une la veille (plus haute sur une issue pour simuler un mouvement)
        for marche, issues in (("1X2", ["1", "N", "2"]), ("OU25", ["+2.5", "-2.5"])):
            for x in issues:
                cs = [r[0] for r in con.execute("SELECT cote FROM cotes WHERE match_id=? AND marche=? AND issue=?", (mid, marche, x))]
                moy = sum(cs) / len(cs)
                ancien = moy * (1.12 if (k == 2 and x == "1") else 1 + rng.normal(0, 0.02))
                con.execute("INSERT INTO cotes_historique VALUES (?,?,?,?,?,?,?)", (mid, marche, x, ancien, ancien, None, iso(now - timedelta(days=1))))
                con.execute("INSERT INTO cotes_historique VALUES (?,?,?,?,?,?,?)", (mid, marche, x, moy, max(cs), None, iso(now)))
        p1, pn = vrai["1"] * np.exp(rng.normal(0, .1)), vrai["N"]
        p2 = vrai["2"] * np.exp(rng.normal(0, .1))
        s = p1 + pn + p2
        con.execute("INSERT INTO elo_probas VALUES (?,?,?,?,?)", (mid, p1 / s, pn / s, p2 / s, maintenant()))
        avenir.append(mid)
        mid += 1
    for e in eqs:
        con.execute("INSERT INTO elo_notes VALUES (?,?,?,?)", (lig, e, 1600 + 300 * FORCE[lig][e][0] - 200 * FORCE[lig][e][1], maintenant()))
# un match de Ligue des champions 3 jours avant pour tester la fatigue
con.execute("INSERT INTO matchs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (mid, "CL", 2026, 5, iso(now - timedelta(days=2)), "FINISHED", EQUIPES["PL"][0], "Real Ficticio", 2, 1, maintenant()))
con.commit()

log = print
agent_modele.executer(con, log)
agent_contexte.executer(con, log)
agent_juge.executer(con, log)
agent_value.executer(con, log)
# un pari test du robot réglé, pour remplir l'historique
r = con.execute("SELECT id FROM matchs WHERE statut='FINISHED' AND ligue='PL' ORDER BY date_utc DESC LIMIT 1").fetchone()
con.execute("INSERT INTO paris (match_id, marche, issue, cote, proba, avantage, mise, cree, cote_cloture) "
            "VALUES (?,?,?,?,?,?,?,?,?)", (r[0], "1X2", "1", 2.1, .5, .05, 10, maintenant(), 1.95))
agent_suivi.executer(con, log)
for nom in ("Calendrier", "Cotes", "Elo", "xG", "Profil de jeu"):
    etat(con, nom, "ok", "Démonstration : données fictives")

# Testeur sur un faux historique (format football-data.co.uk)
def fausse_saison(lig, nb):
    out, eqs = [], EQUIPES[lig]
    d0 = now - timedelta(days=400)
    for j in range(nb):
        ordre = rng.permutation(len(eqs))
        for k in range(len(eqs) // 2):
            d, e = eqs[ordre[2 * k]], eqs[ordre[2 * k + 1]]
            lh, la = lambdas(lig, d, e)
            M = np.outer(poisson.pmf(np.arange(11), lh), poisson.pmf(np.arange(11), la)); X, Y = np.indices(M.shape)
            v = [M[X > Y].sum(), np.trace(M), M[X < Y].sum()]
            pin = [1 / (x * np.exp(rng.normal(0, .03)) * 1.025) for x in v]
            b365 = [1 / (x * np.exp(rng.normal(0, .06)) * 1.06) for x in v]
            out.append({"date": d0 + timedelta(days=7 * j), "dom": d, "ext": e, "bd": int(rng.poisson(lh)),
                        "be": int(rng.poisson(la)), "marche": pin, "classique": b365, "max": [c * 1.03 for c in b365],
                        "cloture": pin, "ou_marche": [None, None], "ou_classique": [None, None], "ou_cloture": [None, None]})
    return out
hist = fausse_saison("PL", 20)
test = fausse_saison("PL", 38)
for m in test:
    m["date"] += timedelta(days=150)
res = agent_testeur.resumer(agent_testeur.backtest(hist, test))
from agents.base_donnees import memo_set  # noqa: E402
memo_set(con, "testeur", {"date": now.strftime("%Y-%m-%d"), "periode": "démo", "global": res,
                          "par_ligue": [res | {"nom": "Premier League (démo)"}], "verdict": agent_testeur.verdict(res)})
etat(con, "Testeur", "ok", agent_testeur.verdict(res))
print("Testeur :", res)

agent_export.executer(con, log)
data = json.load(open(os.environ["DATA_JSON"]))
data["demo"] = True
json.dump(data, open(os.environ["DATA_JSON"], "w"), ensure_ascii=False, separators=(",", ":"))
print("Taille data_demo.json :", os.path.getsize(os.environ["DATA_JSON"]) // 1024, "Ko")
print("Exemple de match :", json.dumps({k: v for k, v in data["matchs"][0].items() if k not in ("matrice", "contexte")}, ensure_ascii=False)[:600])
