"""
Réglages du système. Les clés secrètes ne s'écrivent PAS ici :
elles se rangent dans les "Secrets" GitHub (voir le guide).
"""
import os

# Championnats suivis
#   fd       = code football-data.org (calendrier, résultats)
#   odds     = code The Odds API (cotes)
#   fdcouk   = code football-data.co.uk (tirs, corners, cartons + historique du testeur)
#   understat= nom Understat (xG) — None = pas de xG gratuit pour ce championnat
#   pays     = code ClubElo
LIGUES = {
    "PL":  {"nom": "Premier League", "odds": "soccer_epl",                    "fdcouk": "E0",  "understat": "EPL",        "pays": "ENG", "relegues": 3, "europe": 5},
    "PD":  {"nom": "Liga",           "odds": "soccer_spain_la_liga",          "fdcouk": "SP1", "understat": "La_liga",    "pays": "ESP", "relegues": 3, "europe": 6},
    "SA":  {"nom": "Serie A",        "odds": "soccer_italy_serie_a",          "fdcouk": "I1",  "understat": "Serie_A",    "pays": "ITA", "relegues": 3, "europe": 6},
    "BL1": {"nom": "Bundesliga",     "odds": "soccer_germany_bundesliga",     "fdcouk": "D1",  "understat": "Bundesliga", "pays": "GER", "relegues": 3, "europe": 6},
    "FL1": {"nom": "Ligue 1",        "odds": "soccer_france_ligue_one",       "fdcouk": "F1",  "understat": "Ligue_1",    "pays": "FRA", "relegues": 3, "europe": 5},
    "DED": {"nom": "Eredivisie",     "odds": "soccer_netherlands_eredivisie", "fdcouk": "N1",  "understat": None,         "pays": "NED", "relegues": 3, "europe": 5},
}

FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "")
ODDS_API_KEY      = os.getenv("ODDS_API_KEY", "")
MODE              = os.getenv("MODE", "matin")      # "matin" ou "soir" (relevé de cotes du soir)

# Poids du "juge" (comment on mélange les 4 analystes). Le marché pèse le plus :
# les bookmakers sont très bien informés, nos modèles servent à repérer leurs erreurs.
POIDS = {"marche": 0.45, "buts": 0.20, "xg": 0.20, "elo": 0.15}

# Sélection des conseils
AVANTAGE_MIN   = 0.03   # le juge doit voir au moins 3 % de plus que la meilleure cote du marché
COTE_MIN, COTE_MAX = 1.50, 4.00
MAX_CONSEILS_JOUR = 5
MARGE_SECURITE = 0.05   # cote minimale demandée = 5 % au-dessus de la cote juste
MISE_ROBOT     = 10.0   # le robot teste ses conseils avec 10 CHF virtuels

# Modèles
DECAY_XI = 0.0019
MIN_MATCHS_LIGUE = 40
JOURS_A_VENIR = 7
BAISSE_ALERTE = 0.08    # alerte si une cote baisse de 8 % ou plus

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.getenv("DB_PATH", os.path.join(DOSSIER, "data", "paris.db"))
DATA_JSON = os.getenv("DATA_JSON", os.path.join(DOSSIER, "docs", "data.json"))
