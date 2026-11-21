"""Base de données SQLite partagée par tous les agents + journal d'état des agents."""
import json
import os
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS matchs (
    id INTEGER PRIMARY KEY, ligue TEXT, saison INTEGER, journee INTEGER,
    date_utc TEXT, statut TEXT, equipe_dom TEXT, equipe_ext TEXT,
    buts_dom INTEGER, buts_ext INTEGER, maj TEXT);
CREATE INDEX IF NOT EXISTS ix_matchs ON matchs(ligue, date_utc);

CREATE TABLE IF NOT EXISTS cotes (
    match_id INTEGER, bookmaker TEXT, marche TEXT, issue TEXT, cote REAL, maj TEXT,
    PRIMARY KEY (match_id, bookmaker, marche, issue));

CREATE TABLE IF NOT EXISTS cotes_historique (
    match_id INTEGER, marche TEXT, issue TEXT, moyenne REAL, meilleure REAL, pinnacle REAL, ts TEXT,
    PRIMARY KEY (match_id, marche, issue, ts));

CREATE TABLE IF NOT EXISTS elo_probas (match_id INTEGER PRIMARY KEY, p1 REAL, pn REAL, p2 REAL, maj TEXT);
CREATE TABLE IF NOT EXISTS elo_notes (ligue TEXT, equipe TEXT, elo REAL, maj TEXT, PRIMARY KEY (ligue, equipe));

CREATE TABLE IF NOT EXISTS xg_matchs (
    ligue TEXT, date_utc TEXT, equipe_dom TEXT, equipe_ext TEXT, xg_dom REAL, xg_ext REAL,
    PRIMARY KEY (ligue, date_utc, equipe_dom));

CREATE TABLE IF NOT EXISTS profil_matchs (
    ligue TEXT, date TEXT, equipe_dom TEXT, equipe_ext TEXT,
    bd INTEGER, be INTEGER, tirs_d INTEGER, tirs_e INTEGER, cadres_d INTEGER, cadres_e INTEGER,
    corners_d INTEGER, corners_e INTEGER, jaunes_d INTEGER, jaunes_e INTEGER,
    rouges_d INTEGER, rouges_e INTEGER, fautes_d INTEGER, fautes_e INTEGER, arbitre TEXT,
    PRIMARY KEY (ligue, date, equipe_dom));

CREATE TABLE IF NOT EXISTS predictions (
    match_id INTEGER, modele TEXT,             -- 'buts' ou 'xg'
    p_dom REAL, p_nul REAL, p_ext REAL, p_over25 REAL, p_btts REAL,
    xg_dom REAL, xg_ext REAL, matrice TEXT, maj TEXT,
    PRIMARY KEY (match_id, modele));

CREATE TABLE IF NOT EXISTS verdicts (           -- décision du juge
    match_id INTEGER PRIMARY KEY, p1 REAL, pn REAL, p2 REAL, p_over25 REAL,
    modeles TEXT, pieges TEXT, confiance TEXT, matrice TEXT, maj TEXT);

CREATE TABLE IF NOT EXISTS paris (              -- paris test du robot (argent virtuel)
    id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER, marche TEXT, issue TEXT,
    cote REAL, proba REAL, avantage REAL, mise REAL,
    statut TEXT DEFAULT 'en attente', gain REAL DEFAULT 0, cote_cloture REAL, cree TEXT,
    UNIQUE (match_id));

CREATE TABLE IF NOT EXISTS etat_agents (nom TEXT PRIMARY KEY, etat TEXT, detail TEXT, maj TEXT);
CREATE TABLE IF NOT EXISTS memo (cle TEXT PRIMARY KEY, valeur TEXT);
"""


def maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def connexion(chemin=None):
    chemin = chemin or config.DB_PATH
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    con = sqlite3.connect(chemin)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def etat(con, nom, etat_, detail):
    con.execute("INSERT OR REPLACE INTO etat_agents VALUES (?,?,?,?)", (nom, etat_, detail, maintenant()))
    con.commit()


def memo_get(con, cle, defaut=None):
    r = con.execute("SELECT valeur FROM memo WHERE cle=?", (cle,)).fetchone()
    return json.loads(r[0]) if r else defaut


def memo_set(con, cle, valeur):
    con.execute("INSERT OR REPLACE INTO memo VALUES (?,?)", (cle, json.dumps(valeur)))
    con.commit()


def saison_en_cours(d=None):
    d = d or datetime.now(timezone.utc)
    return d.year if d.month >= 7 else d.year - 1
