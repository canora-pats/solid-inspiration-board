#!/usr/bin/env python3
"""
Solid Inspiration collector v2.

Collect image + link candidates from configured search/result pages,
download images locally into images/collected/, and append auto-collected
cards to data.json while keeping manually curated cards safe.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_JSON = ROOT / "data.json"
SOURCES_JSON = ROOT / "sources.json"
IMAGE_DIR = ROOT / "images" / "collected"

USER_AGENT = "SolidInspirationBot/0.2 (personal style board; non-commercial curation)"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/*,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
})

@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    image_url: str

def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def normalize_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def clean_title(text: str | None, fallback: str) -> str:
    text = normalize_space(text)
    text = re.sub(r"^(画像|Image|写真|Product image|商品画像)\s*[:：]?\s*", "", text, flags=re.I)
    text = text.strip(" -_|｜")
    if not text:
        text = fallback
    return text[:120]

def absolutize(base_url: str, value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value or value.startswith("data:") or value.startswith("javascript:"):
        return None
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base_url, value)

def pick_from_srcset(srcset: str | None) -> str | None:
    if not srcset:
        return None
    candidates = []
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        weight = 0
        if len(bits) > 1:
            m = re.match(r"(\d+)(w|x)", bits[1])
            if m:
                weight = int(m.group(1))
        candidates.append((weight, url))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]

def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    keep = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        low = k.lower()
        if low.startswith("utm_") or low in {"gclid", "fbclid", "msclkid", "ref", "spm"}:
            continue
        keep.append((k, v))
    query = urlencode(keep, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.params, query, ""))

def image_extension(resp: requests.Response, image_url: str) -> str:
    content_type = (resp.headers.get("content-type") or "").split(";")[0].lower().strip()
    ext = mimetypes.guess_extension(content_type) or ""
    if ext == ".jpe":
        ext = ".jpg"
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ext
    path_ext = Path(urlparse(image_url).path).suffix.lower()
    if path_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return path_ext
    return ".jpg"

def find_nearest_link(img, base_url: str) -> str | None:
    parent = img
    for _ in range(7):
        parent = parent.parent
        if parent is None:
            return None
        if getattr(parent, "name", None) == "a":
            return absolutize(base_url, parent.get("href"))
    return None

def nearby_title(img, fallback: str) -> str:
    alt = img.get("alt")
    if normalize_space(alt):
        return clean_title(alt, fallback)
    parent = img
    for _ in range(5):
        parent = parent.parent
        if parent is None:
            break
        for selector in ["h1", "h2", "h3", "h4", "[class*=title]", "[class*=name]", "[class*=product]"]:
            found = parent.select_one(selector)
            if found:
                title = clean_title(found.get_text(" ", strip=True), fallback)
                if title != fallback:
                    return title
    link = find_nearest_link(img, "")
    if link:
        segment = Path(urlparse(link).path).name.replace("-", " ").replace("_", " ")
        if segment:
            return clean_title(segment, fallback)
    return fallback

def is_probably_product_image(image_url: str, link_url: str) -> bool:
    lower_img = image_url.lower()
    lower_link = link_url.lower()
    if lower_img.endswith(".svg"):
        return False
    blocked = ["logo", "icon", "sprite", "placeholder", "loading", "payment", "facebook", "instagram", "line", "twitter"]
    if any(word in lower_img for word in blocked):
        return False
    positive_link_parts = ["/products/", "/product/", "/items/", "/item/", "/listing/", "/shop/", "/collections/", "/goods/"]
    if any(part in lower_link for part in positive_link_parts):
        return True
    positive_image_parts = ["cdn", "shopify", "etsystatic", "product", "products", "item", "files"]
    return any(part in lower_img for part in positive_image_parts)

def extract_with_selectors(soup: BeautifulSoup, source: dict[str, Any]) -> list[Candidate]:
    selectors = source.get("selectors") or {}
    item_selector = selectors.get("item")
    if not item_selector:
        return []
    base_url = source["url"]
    fallback = source["title"]
    results = []
    seen = set()
    for item in soup.select(item_selector):
        link_el = item.select_one(selectors.get("link", "a"))
        img_el = item.select_one(selectors.get("image", "img"))
        title_el = item.select_one(selectors.get("title", "")) if selectors.get("title") else None
        if not link_el or not img_el:
            continue
        link = absolutize(base_url, link_el.get("href"))
        raw_img = img_el.get("src") or img_el.get("data-src") or img_el.get("data-original") or img_el.get("data-lazy-src") or pick_from_srcset(img_el.get("srcset")) or pick_from_srcset(img_el.get("data-srcset"))
        image = absolutize(base_url, raw_img)
        title = clean_title(title_el.get_text(" ", strip=True) if title_el else img_el.get("alt"), fallback)
        if not link or not image:
            continue
        key = (canonical_url(link), image)
        if key in seen:
            continue
        seen.add(key)
        results.append(Candidate(title=title, url=link, image_url=image))
    return results

def extract_candidates(source: dict[str, Any]) -> list[Candidate]:
    url = source["url"]
    max_items = int(source.get("max_items", 8))
    resp = SESSION.get(url, timeout=35)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    candidates = extract_with_selectors(soup, source)
    if candidates:
        return candidates[:max_items]
    candidates = []
    seen = set()
    fallback = source.get("title", source["id"])
    for img in soup.find_all("img"):
        raw_img = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy-src") or pick_from_srcset(img.get("srcset")) or pick_from_srcset(img.get("data-srcset"))
        image_url = absolutize(url, raw_img)
        link_url = find_nearest_link(img, url)
        if not image_url or not link_url:
            continue
        if not is_probably_product_image(image_url, link_url):
            continue
        title = nearby_title(img, fallback)
        key = (canonical_url(link_url), image_url)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(Candidate(title=title, url=link_url, image_url=image_url))
        if len(candidates) >= max_items:
            break
    if not candidates:
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        og_img = absolutize(url, og.get("content") if og else None)
        if og_img:
            candidates.append(Candidate(title=fallback, url=url, image_url=og_img))
    return candidates[:max_items]

def download_image(image_url: str, source_id: str, index: int, settings: dict[str, Any]) -> str | None:
    try:
        resp = SESSION.get(image_url, timeout=35)
        resp.raise_for_status()
        content_type = (resp.headers.get("content-type") or "").lower()
        if "image" not in content_type:
            return None
        content = resp.content
        min_bytes = int(settings.get("image_min_bytes", 8000))
        max_bytes = int(settings.get("image_max_bytes", 6000000))
        if len(content) < min_bytes:
            return None
        if len(content) > max_bytes:
            print(f"Skip large image: {image_url} ({len(content)} bytes)")
            return None
        digest = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:12]
        ext = image_extension(resp, image_url)
        filename = f"{source_id}-{index:02d}-{digest}{ext}"
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        path = IMAGE_DIR / filename
        path.write_bytes(content)
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except Exception as exc:
        print(f"Image download failed: {image_url} ({exc})")
        return None

def remove_previous_auto_items(data: dict[str, Any]) -> set[str]:
    old_images = set()
    kept = []
    for item in data.get("items", []):
        if "auto-collected" in item.get("tags", []):
            img = item.get("image")
            if isinstance(img, str) and img.startswith("images/collected/"):
                old_images.add(img)
        else:
            kept.append(item)
    data["items"] = kept
    return old_images

def make_card(source: dict[str, Any], candidate: Candidate, image_path: str, index: int, collected_at: str) -> dict[str, Any]:
    base_score = int(source.get("base_score", 80))
    score = max(60, base_score - min(index, 10))
    source_title = source.get("title", source["id"])
    title = candidate.title if candidate.title and candidate.title != source_title else f"{source_title} #{index + 1}"
    featured_limit = int(source.get("featured_limit", 0))
    tags = list(dict.fromkeys(source.get("tags", []) + ["collected-image"]))
    return {
        "title": title,
        "url": canonical_url(candidate.url),
        "category": source.get("category", "Search Shelves"),
        "score": score,
        "description": f"{source_title} から自動収集した画像付き候補。",
        "reason": "検索結果から画像とリンクを抽出し、ローカル画像として保存したカードです。内容は目視確認してください。",
        "image": image_path,
        "featured": index < featured_limit and score >= 82,
        "source_id": source["id"],
        "collected_at": collected_at,
        "tags": tags,
    }

def cleanup_unreferenced_images(valid_paths: set[str], old_auto_paths: set[str]) -> None:
    for rel in old_auto_paths:
        if rel in valid_paths:
            continue
        path = ROOT / rel
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except Exception as exc:
            print(f"Could not delete old image {path}: {exc}")

def main() -> None:
    if not DATA_JSON.exists():
        raise FileNotFoundError("data.json not found")
    if not SOURCES_JSON.exists():
        raise FileNotFoundError("sources.json not found")
    data = load_json(DATA_JSON)
    config = load_json(SOURCES_JSON)
    settings = config.get("settings", {})
    interval = float(settings.get("request_interval_seconds", 1.2))
    max_total = int(settings.get("max_total_auto_items", 60))
    collected_at = now_iso()
    old_auto_paths = remove_previous_auto_items(data)
    new_items: list[dict[str, Any]] = []
    seen_card_urls = {canonical_url(item.get("url", "")) for item in data.get("items", []) if item.get("url")}
    seen_image_urls: set[str] = set()
    for source in config.get("sources", []):
        if len(new_items) >= max_total:
            break
        print(f"Collecting: {source['title']} <{source['url']}>")
        try:
            candidates = extract_candidates(source)
        except Exception as exc:
            print(f"Source failed: {source.get('id', 'unknown')} ({exc})")
            continue
        source_added = 0
        for candidate in candidates:
            if len(new_items) >= max_total:
                break
            card_url = canonical_url(candidate.url)
            if card_url in seen_card_urls or candidate.image_url in seen_image_urls:
                continue
            image_path = download_image(candidate.image_url, source["id"], source_added, settings)
            if not image_path:
                continue
            card = make_card(source, candidate, image_path, source_added, collected_at)
            new_items.append(card)
            seen_card_urls.add(card_url)
            seen_image_urls.add(candidate.image_url)
            source_added += 1
            time.sleep(interval)
        print(f"  added {source_added} items")
        time.sleep(interval)
    existing = data.get("items", [])
    data["items"] = sorted(existing + new_items, key=lambda item: item.get("score", 0), reverse=True)
    valid_paths = {item.get("image") for item in data.get("items", []) if isinstance(item.get("image"), str) and item.get("image", "").startswith("images/collected/")}
    cleanup_unreferenced_images(valid_paths, old_auto_paths)
    save_json(DATA_JSON, data)
    print(f"Added {len(new_items)} auto-collected items.")
    print(f"Collected at {collected_at}")

if __name__ == "__main__":
    main()
