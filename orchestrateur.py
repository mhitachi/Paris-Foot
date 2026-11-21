"""CHEF D'ORCHESTRE — lance tous les agents dans l'ordre. Si un agent plante, les autres continuent.
  python orchestrateur.py              -> tout (relevé du matin)
  MODE=soir python orchestrateur.py    -> relevé du soir (cotes + mise à jour)
  python orchestrateur.py --hors-ligne -> recalcule sans Internet
  python orchestrateur.py --test       -> force le testeur"""
import sys
import time
import traceback

import config
from agents import (agent_contexte, agent_cotes, agent_elo, agent_export, agent_juge, agent_matchs, agent_modele,
                    agent_profil, agent_suivi, agent_testeur, agent_value, agent_xg)
from agents.base_donnees import connexion, etat

#        nom affiché, agent, besoin d'Internet, aussi le soir ?
ETAPES = [
    ("Calendrier", agent_matchs, True, True),
    ("Cotes", agent_cotes, True, True),
    ("Elo", agent_elo, True, False),
    ("xG", agent_xg, True, False),
    ("Profil de jeu", agent_profil, True, False),
    ("Modèles", agent_modele, False, False),
    ("Contexte", agent_contexte, False, False),
    ("Juge", agent_juge, False, True),
    ("Suivi", agent_suivi, False, True),
    ("Conseils", agent_value, False, True),
    ("Testeur", agent_testeur, True, False),
    ("Application", agent_export, False, True),
]


def main():
    hors_ligne = "--hors-ligne" in sys.argv
    soir = config.MODE == "soir"
    con = connexion()
    for nom, agent, reseau, le_soir in ETAPES:
        if (hors_ligne and reseau) or (soir and not le_soir):
            continue
        print(f"▶ {nom}")
        t = time.time()
        try:
            if agent is agent_testeur:
                agent.executer(con, print, forcer="--test" in sys.argv)
            else:
                agent.executer(con, print)
        except Exception as ex:
            traceback.print_exc()
            etat(con, nom, "erreur", f"{type(ex).__name__} : {str(ex)[:120]}")
        print(f"  ({time.time() - t:.1f}s)")
    con.close()


if __name__ == "__main__":
    main()
