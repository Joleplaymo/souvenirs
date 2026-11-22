"""Télécharge les morceaux Incompetech du catalogue (music/catalogue.json) absents du dossier cible.

Usage : python tools/fetch_music.py [--dest DIR]
Par défaut : DATA_DIR/music/library. Les MP3 ne sont jamais versionnés.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "backend", ROOT):  # checkout : backend/app ; image Docker : app/ à la racine
    sys.path.insert(0, str(p))

from app import config  # noqa: E402
from app.pipeline import music  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", help="dossier de destination (défaut : DATA_DIR/music/library)")
    args = ap.parse_args()
    config.MUSIC_DIR = ROOT / "music"
    res = music.fetch_missing(dest=args.dest)
    print(f"{res['ok']} téléchargés, {res['skipped']} déjà présents, {res['failed']} échecs")
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
