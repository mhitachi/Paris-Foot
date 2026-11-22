"""Outil de l'agent presse (Claude). Deux usages :

  python presse_a_faire.py
      -> affiche "RIEN" s'il n'y a aucun match à lire maintenant,
         sinon une ligne JSON par match à lire (au maximum ce qu'il reste du quota du jour).
         Un match est à lire s'il a un conseil, commence dans 1h à 3h, et n'a pas encore été lu.

  python presse_a_faire.py --ajouter lecture.json
      -> ajoute la lecture d'UN match (format décrit dans presse_prompt.md) à docs/presse.json,
         et efface les lectures de plus de 3 jours.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ICI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ICI, "docs", "data.json")
PRESSE = os.path.join(ICI, "docs", "presse.json")
MAX_PAR_JOUR = 5
TZ = ZoneInfo("Europe/Zurich")


def lire(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def a_faire():
    now = datetime.now(timezone.utc)
    data, presse = lire(DATA, {"matchs": []}), lire(PRESSE, {"matchs": {}})
    deja = presse.get("matchs", {})
    aujourdhui = now.astimezone(TZ).date().isoformat()
    lus_aujourdhui = sum(1 for p in deja.values() if p.get("lu_le") == aujourdhui)
    reste = MAX_PAR_JOUR - lus_aujourdhui
    out = []
    for m in data.get("matchs", []):
        debut = datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
        if m.get("conseil") and str(m["id"]) not in deja and timedelta(hours=1) <= debut - now <= timedelta(hours=3):
            out.append({"id": m["id"], "championnat": m["ligue_nom"], "coup_envoi": debut.astimezone(TZ).strftime("%d.%m %H:%M"),
                        "domicile": m["dom"], "exterieur": m["ext"]})
    out = out[:max(reste, 0)]
    if not out:
        print("RIEN")
    for o in out:
        print(json.dumps(o, ensure_ascii=False))


def ajouter(fichier):
    lecture = lire(fichier, None)
    if not lecture or "id" not in lecture:
        sys.exit("Fichier de lecture invalide : il faut au moins le champ \"id\".")
    presse = lire(PRESSE, {"matchs": {}})
    limite = (datetime.now(TZ).date() - timedelta(days=3)).isoformat()
    presse["matchs"] = {k: v for k, v in presse.get("matchs", {}).items() if v.get("lu_le", "") >= limite}
    mid = str(lecture.pop("id"))
    lecture["lu_le"] = datetime.now(TZ).date().isoformat()
    presse["matchs"][mid] = lecture
    presse["maj"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(PRESSE, "w", encoding="utf-8") as f:
        json.dump(presse, f, ensure_ascii=False, indent=1)
    print(f"Lecture du match {mid} ajoutée.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--ajouter":
        ajouter(sys.argv[2])
    else:
        a_faire()
