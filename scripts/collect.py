#!/usr/bin/env python3
"""
Collect image thumbnails and links for Solid Inspiration.

This script:
- reads sources.json
- fetches search/result pages
- extracts candidate image + link pairs heuristically
- downloads images into images/collected/
- removes old auto-collected cards from data.json
- appends fresh auto-collected cards

Notes:
- Respect source sites' terms and robots policies.
- This is intentionally conservative: limited source count and limited item count.
- For fully robust Etsy support, use Etsy Open API v3 later.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_JSON = ROOT / "data.json"
SOURCES_JSON = ROOT / "sources.json"
IMAGE_DIR = ROOT / "images" / "collected"

USER_AGENT = (
    "SolidInspirationBot/0.1 "
    "(personal style board; contact via GitHub repository owner)"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/*,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
})


@dataclass
class Candidate:
    title: str
    url: str
    image_url: str


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def absolutize(base_url: str, value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value or value.startswith("data:"):
        return None
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base_url, value)


def pick_from_srcset(srcset: str | None) -> str | None:
    if not srcset:
        return None
    parts = [p.strip() for p in srcset.split(",") if p.strip()]
    if not parts:
        return None
    # Usually the last candidate is the largest.
    return parts[-1].split()[0]


def clean_title(text: str | None, fallback: str) -> str:
    if not text:
        return fallback
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(画像|Image|写真)\s*[:：]?\s*", "", text, flags=re.I)
    return text[:120] if text else fallback


def find_nearest_link(img, base_url: str) -> str | None:
    parent = img
    for _ in range(6):
        parent = parent.parent
        if parent is None:
            return None
        if getattr(parent, "name", None) == "a":
            href = parent.get("href")
            return absolutize(base_url, href)
    return None


def extract_candidates(source: dict) -> list[Candidate]:
    url = source["url"]
    max_items = int(source.get("max_items", 8))
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    candidates: list[Candidate] = []
    seen: set[tuple[str, str]] = set()

    # 1) Prefer images that are inside links.
    for img in soup.find_all("img"):
        raw_img = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
            or pick_from_srcset(img.get("srcset"))
            or pick_from_srcset(img.get("data-srcset"))
        )
        image_url = absolutize(url, raw_img)
        link_url = find_nearest_link(img, url)

        if not image_url or not link_url:
            continue

        parsed_img = urlparse(image_url)
        if not parsed_img.netloc:
            continue

        # Skip tiny common assets and SVG logos where possible.
        lower = image_url.lower()
        if any(x in lower for x in ["logo", "icon", "sprite", "placeholder"]):
            continue
        if lower.endswith(".svg"):
            continue

        alt = img.get("alt")
        title = clean_title(alt, source["title"])

        key = (link_url, image_url)
        if key in seen:
            continue
        seen.add(key)

        candidates.append(Candidate(title=title, url=link_url, image_url=image_url))
        if len(candidates) >= max_items:
            return candidates

    # 2) Fallback: Open Graph image for the source page itself.
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    og_img = absolutize(url, og.get("content") if og else None)
    if og_img:
        candidates.append(Candidate(title=source["title"], url=url, image_url=og_img))

    return candidates[:max_items]


def extension_from_response(resp: requests.Response, image_url: str) -> str:
    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = mimetypes.guess_extension(content_type) or ""
    if ext in [".jpe"]:
        ext = ".jpg"
    if ext:
        return ext

    path_ext = Path(urlparse(image_url).path).suffix.lower()
    if path_ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        return path_ext

    return ".jpg"


def download_image(image_url: str, source_id: str, index: int) -> str | None:
    try:
        resp = SESSION.get(image_url, timeout=30)
        resp.raise_for_status()
        content_type = (resp.headers.get("content-type") or "").lower()
        if "image" not in content_type:
            return None

        digest = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:12]
        ext = extension_from_response(resp, image_url)
        filename = f"{source_id}-{index:02d}-{digest}{ext}"
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        path = IMAGE_DIR / filename
        path.write_bytes(resp.content)

        return str(path.relative_to(ROOT)).replace("\\", "/")
    except Exception as exc:
        print(f"Image download failed: {image_url} ({exc})")
        return None


def remove_previous_auto_items(data: dict) -> None:
    items = data.get("items", [])
    data["items"] = [
        item for item in items
        if "auto-collected" not in item.get("tags", [])
    ]


def make_card(source: dict, candidate: Candidate, image_path: str, index: int) -> dict:
    base_score = int(source.get("base_score", 80))
    score = max(60, base_score - min(index, 10))
    source_title = source.get("title", source["id"])
    title = candidate.title if candidate.title and candidate.title != source_title else f"{source_title} #{index + 1}"

    tags = list(dict.fromkeys(source.get("tags", []) + ["collected-image"]))

    return {
        "title": title,
        "url": candidate.url,
        "category": source.get("category", "Search Shelves"),
        "score": score,
        "description": f"{source_title} から自動収集した画像付き候補。",
        "reason": "検索結果から画像とリンクを抽出し、ローカル画像として保存したカードです。内容は目視確認してください。",
        "image": image_path,
        "featured": score >= 86,
        "tags": tags,
    }


def main() -> None:
    if not DATA_JSON.exists():
        raise FileNotFoundError("data.json not found")
    if not SOURCES_JSON.exists():
        raise FileNotFoundError("sources.json not found")

    data = load_json(DATA_JSON)
    config = load_json(SOURCES_JSON)

    remove_previous_auto_items(data)

    new_items: list[dict] = []
    for source in config.get("sources", []):
        print(f"Collecting: {source['title']} <{source['url']}>")
        try:
            candidates = extract_candidates(source)
        except Exception as exc:
            print(f"Source failed: {source['id']} ({exc})")
            continue

        for index, candidate in enumerate(candidates):
            image_path = download_image(candidate.image_url, source["id"], index)
            if not image_path:
                continue
            new_items.append(make_card(source, candidate, image_path, index))
            time.sleep(0.8)

        time.sleep(1.2)

    # Keep new items near the top but after manually curated very high-score cards.
    existing = data.get("items", [])
    data["items"] = sorted(existing + new_items, key=lambda item: item.get("score", 0), reverse=True)

    save_json(DATA_JSON, data)
    print(f"Added {len(new_items)} auto-collected items.")


if __name__ == "__main__":
    main()
