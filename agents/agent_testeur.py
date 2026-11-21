"""AGENT Testeur — l'examen du système sur les 3 saisons passées, avec les vraies cotes de l'époque.
Données : football-data.co.uk (gratuit). Tourne une fois par semaine (lundi).
Simplification honnête : à l'époque on n'a ni xG ni Elo archivés -> le test utilise le modèle buts + le marché.
Il mesure :
 - le rendement en pariant chez un bookmaker classique (Bet365, proche de ce que propose Jouez Sport),
 - le rendement avec la meilleure cote du marché,
 - la cote de clôture battue (contre Pinnacle, la référence)."""
from datetime import datetime, timedelta, timezone

import config
from agents import agent_profil
from agents.agent_modele import ajuster, matrice_scores, probas
from agents.base_donnees import etat, memo_get, memo_set, saison_en_cours

NOM = "Testeur"
POIDS_MARCHE = 0.45


def f(v):
    try:
        x = float(v)
        return x if x > 1 else None
    except (TypeError, ValueError):
        return None


def preparer(lignes):
    out = []
    for r in lignes:
        d = agent_profil.date_iso(r.get("Date", ""))
        if not d or r.get("FTHG") in (None, "") or not r.get("HomeTeam"):
            continue
        out.append({"date": datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc),
                    "dom": r["HomeTeam"], "ext": r["AwayTeam"], "bd": int(float(r["FTHG"])), "be": int(float(r["FTAG"])),
                    "marche": [f(r.get(k)) for k in ("PSH", "PSD", "PSA")],
                    "classique": [f(r.get(k)) for k in ("B365H", "B365D", "B365A")],
                    "max": [f(r.get(k)) for k in ("MaxH", "MaxD", "MaxA")],
                    "cloture": [f(r.get(k)) for k in ("PSCH", "PSCD", "PSCA")],
                    "ou_marche": [f(r.get("P>2.5")), f(r.get("P<2.5"))],
                    "ou_classique": [f(r.get("B365>2.5")), f(r.get("B365<2.5"))],
                    "ou_cloture": [f(r.get("PC>2.5")), f(r.get("PC<2.5"))]})
    return sorted(out, key=lambda x: x["date"])


def sans_marge(cotes):
    if not all(cotes):
        return None
    inv = [1 / c for c in cotes]
    return [x / sum(inv) for x in inv]


def backtest(historique, a_tester):
    """historique : matchs déjà connus (avant la période) ; a_tester : matchs de la période, triés."""
    paris = []
    connus = list(historique)
    mod, date_fit = None, None
    for m in a_tester:
        if mod is None or (m["date"] - date_fit).days >= 28:
            base = [(x["dom"], x["ext"], x["bd"], x["be"], x["date"]) for x in connus
                    if (m["date"] - x["date"]).days <= 730]
            if len(base) >= config.MIN_MATCHS_LIGUE:
                mod, date_fit = ajuster(base, m["date"]), m["date"]
        if mod and m["dom"] in mod["equipes"] and m["ext"] in mod["equipes"] and sum(
                1 for x in connus if x["date"].year >= m["date"].year - 1 and m["dom"] in (x["dom"], x["ext"])) >= 8:
            M, _, _ = matrice_scores(mod, m["dom"], m["ext"])
            p = probas(M)
            pm = sans_marge(m["marche"])
            if pm:
                juge = [POIDS_MARCHE * a + (1 - POIDS_MARCHE) * b for a, b in zip(pm, (p["p_dom"], p["p_nul"], p["p_ext"]))]
                res = 0 if m["bd"] > m["be"] else 1 if m["bd"] == m["be"] else 2
                options = [(i, juge[i], m["classique"][i], m["max"][i], m["cloture"][i], i == res) for i in range(3)]
                pmo = sans_marge(m["ou_marche"])
                if pmo:
                    po = 0.5 * pmo[0] + 0.5 * p["p_over25"]
                    plus = m["bd"] + m["be"] >= 3
                    options += [("+", po, m["ou_classique"][0], None, m["ou_cloture"][0], plus),
                                ("-", 1 - po, m["ou_classique"][1], None, m["ou_cloture"][1], not plus)]
                choix = [o for o in options if o[2] and config.COTE_MIN <= o[2] <= config.COTE_MAX
                         and o[1] * o[2] - 1 >= config.AVANTAGE_MIN]
                if choix:
                    o = max(choix, key=lambda o: o[1] * o[2])
                    paris.append({"gagne": o[5], "cote": o[2], "max": o[3] or o[2], "cloture": o[4]})
        connus.append(m)
    return paris


def resumer(paris):
    if not paris:
        return {"nb": 0}
    n = len(paris)
    roi = sum((p["cote"] - 1) if p["gagne"] else -1 for p in paris) / n
    roi_max = sum((p["max"] - 1) if p["gagne"] else -1 for p in paris) / n
    clv = [p for p in paris if p["cloture"]]
    return {"nb": n, "gagnes": sum(p["gagne"] for p in paris), "roi": round(float(roi), 4), "roi_meilleure": round(float(roi_max), 4),
            "clv_battu": round(float(sum(p["cote"] > p["cloture"] for p in clv) / len(clv)), 3) if clv else None}


def verdict(r):
    if not r.get("nb"):
        return "Pas assez de données pour juger."
    roi = r["roi"]
    if roi >= 0.02:
        return (f"Sur {r['nb']} paris, le système aurait gagné {roi:+.1%} de ce qui a été misé chez un bookmaker classique. "
                "Encourageant, mais le passé ne garantit pas l'avenir : commence petit.")
    if roi >= -0.02:
        return (f"Sur {r['nb']} paris, le système finit à peu près à l'équilibre ({roi:+.1%}). "
                "C'est déjà mieux que la quasi-totalité des parieurs, qui perdent 5 à 10 %. Sois très sélectif.")
    return (f"Sur {r['nb']} paris, le système aurait perdu {abs(roi):.1%} chez un bookmaker classique. "
            "Sur ces championnats, les cotes sont trop bien calculées : ne suis que les conseils avec la confiance « forte ».")


def executer(con, log, forcer=False):
    der = memo_get(con, "testeur_date")
    now = datetime.now(timezone.utc)
    if not forcer and der and (now - datetime.fromisoformat(der)).days < 6 and now.weekday() != 0:
        log("  test déjà fait cette semaine")
        return
    s = saison_en_cours()
    par_ligue, tous = {}, []
    for code, info in config.LIGUES.items():
        saisons = {}
        for sa in range(s - 4, s):
            try:
                saisons[sa] = preparer(agent_profil.lire(info["fdcouk"], sa))
            except Exception as ex:
                log(f"  {code} {sa}: {type(ex).__name__}")
        if s - 4 not in saisons or len(saisons) < 2:
            continue
        hist = saisons.pop(s - 4)
        a_tester = [m for sa in sorted(saisons) for m in saisons[sa]]
        paris = backtest(hist, a_tester)
        par_ligue[code] = resumer(paris) | {"nom": info["nom"]}
        tous += paris
        log(f"  {info['nom']}: {par_ligue[code]}")
    g = resumer(tous)
    resultat = {"date": now.strftime("%Y-%m-%d"), "periode": f"{s - 3}-{s}", "global": g,
                "par_ligue": list(par_ligue.values()), "verdict": verdict(g)}
    memo_set(con, "testeur", resultat)
    memo_set(con, "testeur_date", now.isoformat())
    etat(con, NOM, "ok" if g.get("nb") else "erreur", resultat["verdict"])
