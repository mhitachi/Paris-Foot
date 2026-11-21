"""AGENT Application — prépare le fichier lu par l'application (docs/data.json)."""
import json
import os
from datetime import datetime, timedelta, timezone

import config
from agents import agent_contexte, agent_suivi
from agents.agent_juge import mouvements, proba_marche
from agents.agent_value import conseil
from agents.base_donnees import etat, memo_get

ORDRE_AGENTS = [
    ("Calendrier", "Récupère tous les matchs et résultats des 6 championnats + Ligue des champions."),
    ("Cotes", "Relève les cotes d'une vingtaine de bookmakers, matin et soir."),
    ("Elo", "Note la force de chaque club, mise à jour après chaque match."),
    ("xG", "Mesure la qualité des occasions créées (5 grands championnats)."),
    ("Profil de jeu", "Tirs, corners, cartons et fautes de chaque équipe."),
    ("Modèle buts", "Analyste : avis basé sur les buts marqués et encaissés (pour information)."),
    ("Modèle xG", "Analyste : avis basé sur la qualité des occasions (pour information)."),
    ("Forme", "Résultats récents, séparés à domicile et à l'extérieur."),
    ("Fatigue", "Jours de repos, matchs enchaînés, Ligue des champions en semaine."),
    ("Enjeu", "Titre, Europe, maintien ou plus rien à jouer."),
    ("Mouvements de cotes", "Repère les cotes qui chutent : souvent une info qui circule."),
    ("Juge", "Fixe le vrai prix de chaque pari grâce à Pinnacle, la référence des pros."),
    ("Détecteur de pièges", "Te prévient quand une analyse est fragile."),
    ("Conseils", "Repère les bookmakers en retard sur Pinnacle : les belles occasions du jour."),
    ("Suivi", "Règle les paris test du robot (argent virtuel)."),
    ("Cote de clôture", "Vérifie si les conseils battent la dernière cote avant le match."),
    ("Testeur", "Rejoue la méthode sur les 3 saisons passées avec les vraies cotes de l'époque."),
]


def executer(con, log):
    now = datetime.now(timezone.utc)
    now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    lim = (now + timedelta(days=config.JOURS_A_VENIR)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tables = {c: agent_contexte.classement(con, c, max([r[0] for r in con.execute(
        "SELECT saison FROM matchs WHERE ligue=?", (c,))] or [0])) for c in config.LIGUES}
    rows = con.execute("""SELECT m.*, v.p1, v.pn, v.p2, v.p_over25, v.modeles, v.pieges, v.confiance, v.matrice,
                          v.match_id FROM matchs m JOIN verdicts v ON v.match_id=m.id
                          WHERE m.date_utc BETWEEN ? AND ? AND m.statut IN ('SCHEDULED','TIMED')
                          ORDER BY m.date_utc""", (now_s, lim)).fetchall()
    matchs = []
    for r in rows:
        pm, best = proba_marche(con, r["id"])
        pmo, best_o = proba_marche(con, r["id"], "OU25")
        b = con.execute("SELECT xg_dom, xg_ext FROM predictions WHERE match_id=? AND modele='buts'", (r["id"],)).fetchone()
        c = conseil(con, r)
        matchs.append({
            "id": r["id"], "ligue": r["ligue"], "ligue_nom": config.LIGUES[r["ligue"]]["nom"],
            "date": r["date_utc"], "dom": r["equipe_dom"], "ext": r["equipe_ext"],
            "proba": {"1": round(r["p1"], 4), "N": round(r["pn"], 4), "2": round(r["p2"], 4)},
            "plus25": round(r["p_over25"], 4),
            "modeles": {k: {i: round(x, 4) for i, x in v.items()} for k, v in json.loads(r["modeles"]).items()},
            "marche_plus25": round(pmo["+2.5"], 4) if pmo else None,
            "meilleures_cotes": (best or {}) | (best_o or {}),
            "buts_attendus": [round(b[0], 2), round(b[1], 2)] if b else None,
            "matrice": json.loads(r["matrice"]),
            "conseil": ({"marche": c["marche"], "issue": c["issue"], "proba": round(c["proba"], 4),
                         "avantage": round(c["avantage"], 4)} if c else None),
            "confiance": r["confiance"], "pieges": json.loads(r["pieges"]),
            "mouvements": mouvements(con, r["id"]),
            "contexte": agent_contexte.contexte_match(con, r, tables),
        })
    # résultats + cotes de clôture des 45 derniers jours (pour régler TES paris dans l'appli)
    resultats = {}
    debut = (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in con.execute("""SELECT id, buts_dom, buts_ext, date_utc, statut FROM matchs WHERE date_utc BETWEEN ? AND ?
                            AND (statut='FINISHED' OR date_utc<=?)""", (debut, lim, now_s)):
        clo = {}
        for h in con.execute("""SELECT issue, moyenne FROM cotes_historique WHERE match_id=? AND ts<=?
                                ORDER BY ts""", (r["id"], r["date_utc"])):
            clo[h["issue"]] = round(h["moyenne"], 2)  # la dernière photo écrase les précédentes
        if r["statut"] == "FINISHED" or clo:
            resultats[str(r["id"])] = {"bd": r["buts_dom"], "be": r["buts_ext"], "statut": r["statut"], "cloture": clo}
    etats = {r["nom"]: dict(r) for r in con.execute("SELECT * FROM etat_agents")}
    agents = [{"nom": n, "role": role, "etat": etats.get(n, {}).get("etat", "inactif"),
               "detail": etats.get(n, {}).get("detail", "Pas encore lancé"), "maj": etats.get(n, {}).get("maj")}
              for n, role in ORDRE_AGENTS]
    data = {"maj": now_s, "demo": False, "matchs": matchs, "resultats": resultats, "agents": agents,
            "robot": agent_suivi.bilan(con), "testeur": memo_get(con, "testeur")}
    os.makedirs(os.path.dirname(config.DATA_JSON), exist_ok=True)
    with open(config.DATA_JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    log(f"  application mise à jour : {len(matchs)} matchs, {sum(1 for m in matchs if m['conseil'])} conseils")
