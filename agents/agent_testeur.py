"""AGENT Testeur — l'examen du système sur les 3 saisons passées, avec les vraies cotes de l'époque.
Données : football-data.co.uk (gratuit). Tourne une fois par semaine (lundi).
Méthode testée : le vrai prix vient de Pinnacle ; on ne parie que quand Bet365 (bookmaker classique,
proche de Jouez Sport) paie au moins 3 % de plus.
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
    """Méthode actuelle : vrai prix = Pinnacle sans marge. On parie chez un bookmaker classique (Bet365)
    seulement quand il paie au moins 3 % de plus que ce vrai prix. (historique : inutilisé, gardé
    pour compatibilité)."""
    paris = []
    for m in a_tester:
        options = []
        pm = sans_marge(m["marche"])
        if pm:
            res = 0 if m["bd"] > m["be"] else 1 if m["bd"] == m["be"] else 2
            pc = sans_marge(m["cloture"])
            options += [(pm[i], m["classique"][i], m["max"][i], (1 / pc[i]) if pc else None, i == res) for i in range(3)]
        pmo = sans_marge(m["ou_marche"])
        if pmo:
            plus = m["bd"] + m["be"] >= 3
            pco = sans_marge(m["ou_cloture"])
            options += [(pmo[0], m["ou_classique"][0], None, (1 / pco[0]) if pco else None, plus),
                        (pmo[1], m["ou_classique"][1], None, (1 / pco[1]) if pco else None, not plus)]
        choix = [o for o in options if o[1] and config.COTE_MIN <= o[1] <= config.COTE_MAX
                 and o[0] * o[1] - 1 >= config.AVANTAGE_MIN]
        if choix:
            o = max(choix, key=lambda o: o[0] * o[1])
            paris.append({"gagne": o[4], "cote": o[1], "max": o[2] or o[1], "cloture": o[3]})
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
    roi, n, clv = r["roi"], r["nb"], r.get("clv_battu")
    txt = f"Sur {n} paris en 3 saisons, le résultat est de {roi:+.1%}. "
    if n < 200:
        txt += "C'est trop peu de paris pour juger sur le résultat : le hasard pèse encore énormément. "
    if clv is not None:
        if clv >= 0.6:
            txt += (f"Le bon signe : ces paris ont battu la cote de clôture de Pinnacle {clv:.0%} du temps. "
                    "C'est le meilleur indicateur des parieurs gagnants sur la durée.")
        else:
            txt += f"Cote de clôture battue seulement {clv:.0%} du temps : la méthode ne trouve pas assez de bons prix."
    return txt


def executer(con, log, forcer=False):
    der = memo_get(con, "testeur_date")
    now = datetime.now(timezone.utc)
    if memo_get(con, "testeur_version") != 3:
        forcer = True  # nouvelle méthode -> on refait l'examen tout de suite
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
    memo_set(con, "testeur_version", 3)
    etat(con, NOM, "ok" if g.get("nb") else "erreur", resultat["verdict"])
