"""Rapprochement des noms d'équipes entre les différentes sources
(ex: 'Manchester United FC' <-> 'Manchester United', 'FC Bayern München' <-> 'Bayern Munich')."""
import re
import unicodedata
from difflib import SequenceMatcher

MOTS_INUTILES = {
    "fc", "cf", "afc", "ac", "as", "ssc", "sc", "sv", "rc", "rcd", "ca", "cd", "ud", "sd",
    "club", "de", "del", "la", "le", "1", "og", "hsc", "losc", "us", "ss", "vfb", "vfl",
    "tsg", "bv", "fk", "calcio", "football", "balompie", "hotspur", "and", "albion",
    "1899", "1909", "1846", "04", "05", "07",
}
ALIAS = {
    "munchen": "munich", "koln": "cologne", "internazionale": "inter",
    "wolverhampton": "wolves", "nottingham": "nottm", "manchester united": "man utd",
    "manchester city": "man city", "paris saint germain": "psg", "paris sg": "psg",
    "atletico madrid": "atletico", "athletic bilbao": "athletic", "borussia monchengladbach": "gladbach",
}


def normaliser(nom):
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = " ".join(s.split())
    for a, b in ALIAS.items():
        s = s.replace(a, b)
    mots = [m for m in s.split() if m not in MOTS_INUTILES]
    return " ".join(mots) or s


def similarite(a, b):
    na, nb = normaliser(a), normaliser(b)
    if na == nb:
        return 1.0
    score = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb and (ta <= tb or tb <= ta):
        score = max(score, 0.85)
    return score
