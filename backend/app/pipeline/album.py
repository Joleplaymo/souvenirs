"""Album photo PDF (A4 paysage) à partir du plan d'album."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import media

TPL = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / "templates"),
                  autoescape=select_autoescape(["html"]))
NEED = {"full": 1, "duo": 2, "trio": 3}


def normalize(plan: dict, photos: dict) -> dict:
    """Valide le plan : photos existantes, une seule utilisation, mises en page cohérentes, 40 pages max."""
    used, pages = set(), []
    for p in (plan or {}).get("pages", []):
        layout = p.get("layout")
        if layout in ("text", "quote"):
            text = (p.get("text") or "").strip()
            if text:
                pages.append({"layout": layout, "photos": [], "heading": (p.get("heading") or "").strip(),
                              "text": text[:900 if layout == "text" else 320], "caption": (p.get("caption") or "").strip()})
            continue
        ids = [i for i in p.get("photos", []) if i in photos and i not in used]
        ids = list(dict.fromkeys(ids))[:3]
        if not ids:
            continue
        used.update(ids)
        pages.append({"layout": {1: "full", 2: "duo", 3: "trio"}[len(ids)], "photos": ids, "heading": "",
                      "text": "", "caption": (p.get("caption") or "").strip()[:160]})
    cover = plan.get("cover_photo") if plan else 0
    if cover not in photos:
        cover = next((i for pg in pages for i in pg["photos"]), 0)
    return {"title": (plan or {}).get("title") or "", "subtitle": (plan or {}).get("subtitle") or "",
            "cover_photo": cover, "pages": pages[:40]}


def photo_ids(album: dict) -> list[int]:
    ids = [i for p in album.get("pages", []) for i in p["photos"]]
    if album.get("cover_photo") and album["cover_photo"] not in ids:
        ids.insert(0, album["cover_photo"])
    return ids


def remove_photo(album: dict, item_id: int) -> dict:
    pages = []
    for p in album["pages"]:
        if item_id in p["photos"]:
            ids = [i for i in p["photos"] if i != item_id]
            if not ids:
                continue
            p = {**p, "photos": ids, "layout": {1: "full", 2: "duo", 3: "trio"}[len(ids)]}
        pages.append(p)
    album = {**album, "pages": pages}
    if album.get("cover_photo") == item_id:
        album["cover_photo"] = next((i for pg in pages for i in pg["photos"]), 0)
    return album


def add_photo(album: dict, item_id: int, caption: str = "") -> dict:
    if item_id in photo_ids(album):
        return album
    page = {"layout": "full", "photos": [item_id], "heading": "", "text": "", "caption": caption}
    album = {**album, "pages": [*album["pages"], page]}
    if not album.get("cover_photo"):
        album["cover_photo"] = item_id
    return album


def render(album: dict, photos: dict, ev, people: list[str], out: Path, dates: str):
    def src(i):
        return media.derived(ev["id"], i, "d").as_uri()

    pages = []
    for p in album["pages"]:
        ids = [i for i in p["photos"] if i in photos]
        if p["layout"] in NEED and not ids:
            continue
        imgs = []
        for i in ids:
            it = photos[i]
            portrait = (it["height"] or 1) > (it["width"] or 1)
            # une photo en portrait seule sur une page paysage est montrée entière plutôt que recadrée
            imgs.append({"src": src(i), "contain": portrait and len(ids) == 1})
        pages.append({**p, "images": imgs, "paragraphs": [x.strip() for x in p["text"].split("\n") if x.strip()]})
    cover = album.get("cover_photo")
    html = TPL.get_template("album.html").render(
        title=album["title"] or ev["name"], subtitle=album["subtitle"] or dates, dates=dates,
        cover=src(cover) if cover in photos else None, pages=pages,
        people=", ".join(people) if people else "tout le groupe")
    from weasyprint import HTML

    tmp = out.with_suffix(".tmp.pdf")
    HTML(string=html, base_url=str(out.parent)).write_pdf(tmp)
    tmp.replace(out)
    return len(pages) + 2
