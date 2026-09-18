#!/usr/bin/env python3
"""Build canonical organization registry from GatorConnect raw dumps."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
GC_BASE = "https://gatorconnect.ufl.edu"


def strip_html(text):
    if not text:
        return None
    t = re.sub(r"<[^>]+>", " ", str(text))
    t = unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def norm_url(url):
    if not url:
        return None
    u = str(url).strip()
    if not u or u.lower() in {"null", "none", "n/a", "#"}:
        return None
    if u.startswith("//"):
        u = "https:" + u
    if not re.match(r"^https?://", u, re.I):
        if "." in u:
            u = "https://" + u
        else:
            return None
    try:
        p = urlparse(u)
        if not p.netloc:
            return None
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = (p.path or "").rstrip("/")
        out = f"https://{host}{path}"
        if p.query:
            out += f"?{p.query}"
        return out
    except Exception:
        return None


def instagram_handle(url):
    u = norm_url(url)
    if not u:
        return None
    m = re.search(r"instagram\.com/([^/?#]+)", u, re.I)
    if not m:
        return None
    handle = m.group(1).strip("/")
    if handle.lower() in {"p", "reel", "reels", "stories", "explore", "accounts", "about", "tv"}:
        return None
    return handle.lstrip("@")


def is_uf_host(url):
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host == "ufl.edu" or host.endswith(".ufl.edu")


def is_gatorconnect(url):
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return "gatorconnect.ufl.edu" in host or "campuslabs.com" in host


def is_link_hub(url):
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == h or host.endswith("." + h) for h in (
        "linktr.ee", "linktree.com", "beacons.ai", "bio.link", "carrd.co", "lnk.bio", "later.com"
    ))


def sm_get(social, *keys):
    if not social:
        return None
    lower = {str(k).lower(): v for k, v in social.items()}
    for k in keys:
        v = social.get(k)
        if v:
            return v
        v = lower.get(k.lower())
        if v:
            return v
    return None


def classify_instagram(detail):
    social = detail.get("socialMedia") or {}
    ig_url = norm_url(sm_get(social, "InstagramUrl", "instagramUrl", "Instagram", "instagram"))
    website = norm_url(sm_get(social, "ExternalWebsite", "externalWebsite", "Website", "website"))
    handle = instagram_handle(ig_url)
    if handle:
        return {
            "handle": handle,
            "url": f"https://www.instagram.com/{handle}/",
            "confidence": "HIGH",
            "match_method": "gatorconnect_explicit_link",
            "evidence": [{"source": "gatorconnect", "field": "socialMedia.InstagramUrl", "value": ig_url}],
        }, website
    handle2 = instagram_handle(website)
    if handle2:
        return {
            "handle": handle2,
            "url": f"https://www.instagram.com/{handle2}/",
            "confidence": "HIGH",
            "match_method": "gatorconnect_external_website_is_instagram",
            "evidence": [{"source": "gatorconnect", "field": "socialMedia.ExternalWebsite", "value": website}],
        }, None
    return {
        "handle": None,
        "url": None,
        "confidence": None,
        "match_method": None,
        "evidence": [],
    }, website


def build_record(bundle):
    search = bundle.get("search") or {}
    detail = bundle.get("detail") or {}
    gc_id = detail.get("id") or search.get("Id") or search.get("id")
    name = (detail.get("name") or search.get("Name") or "").strip()
    short = (detail.get("shortName") or search.get("ShortName") or "").strip() or None
    website_key = detail.get("websiteKey") or search.get("WebsiteKey")
    categories = list(search.get("CategoryNames") or [])
    if not categories:
        ot = detail.get("organizationType")
        if isinstance(ot, dict) and ot.get("name"):
            categories = [ot["name"]]

    ig, website = classify_instagram(detail)
    gc_url = f"{GC_BASE}/organization/{website_key}" if website_key else f"{GC_BASE}/organization/{gc_id}"

    official = None
    uf_page = gc_url
    link_hub = None
    if website and not is_gatorconnect(website):
        if is_link_hub(website):
            link_hub = website
        elif is_uf_host(website):
            uf_page = website
        else:
            official = website

    aliases = []
    if short and short.casefold() != name.casefold():
        aliases.append(short)

    status = detail.get("status") or search.get("Status")
    visibility = detail.get("visibility") or search.get("Visibility")
    needs_review = False
    notes = None
    if status and str(status).lower() not in {"active", "approved"}:
        needs_review = True
        notes = f"non-active status: {status}"

    now = datetime.now(timezone.utc).isoformat()
    social = detail.get("socialMedia") or {}
    return {
        "canonical_id": f"gc-{gc_id}",
        "canonical_name": name,
        "aliases": aliases,
        "gatorconnect": {
            "organization_id": str(gc_id),
            "url": gc_url,
            "website_key": website_key,
            "category": categories,
            "description": strip_html(detail.get("description") or search.get("Description")),
            "summary": strip_html(detail.get("summary") or search.get("Summary")),
            "status": status,
            "visibility": visibility,
            "email": detail.get("email"),
        },
        "web": {
            "official_website": official,
            "uf_page": uf_page,
            "link_hub": link_hub,
        },
        "instagram": ig,
        "matching": {
            "needs_review": needs_review,
            "notes": notes,
        },
        "provenance": [
            {
                "source": "gatorconnect_discovery_search",
                "observed_at": now,
                "url": f"{GC_BASE}/api/discovery/search/organizations",
                "external_id": str(gc_id),
            },
            {
                "source": "gatorconnect_discovery_organization",
                "observed_at": now,
                "url": f"{GC_BASE}/api/discovery/organization/{gc_id}",
                "external_id": str(gc_id),
            },
        ],
        "social_other": {
            "facebook": norm_url(sm_get(social, "FacebookUrl", "facebookUrl")),
            "twitter": norm_url(sm_get(social, "TwitterUrl", "twitterUrl")),
            "linkedin": norm_url(sm_get(social, "LinkedInUrl", "linkedInUrl")),
            "youtube": norm_url(sm_get(social, "YoutubeUrl", "youtubeUrl")),
        },
    }


def validate(records):
    issues = []
    ids = [r["canonical_id"] for r in records]
    if len(ids) != len(set(ids)):
        issues.append({"type": "duplicate_canonical_id", "count": len(ids) - len(set(ids))})

    name_counts = Counter((r.get("canonical_name") or "").casefold() for r in records)
    dup_names = sorted([n for n, c in name_counts.items() if n and c > 1])
    if dup_names:
        issues.append({"type": "duplicate_names", "count": len(dup_names), "examples": dup_names[:20]})

    empty_names = [r["canonical_id"] for r in records if not r.get("canonical_name")]
    if empty_names:
        issues.append({"type": "empty_names", "count": len(empty_names), "ids": empty_names[:20]})

    handle_map = {}
    for r in records:
        h = (r.get("instagram") or {}).get("handle")
        if h:
            handle_map.setdefault(h.casefold(), []).append(r["canonical_id"])
    multi = {h: v for h, v in handle_map.items() if len(v) > 1}
    if multi:
        issues.append({"type": "shared_instagram_handle", "count": len(multi), "handles": dict(list(multi.items())[:30])})

    malformed = []
    for r in records:
        for field, url in [
            ("web.official_website", r["web"].get("official_website")),
            ("web.uf_page", r["web"].get("uf_page")),
            ("web.link_hub", r["web"].get("link_hub")),
            ("instagram.url", r["instagram"].get("url")),
        ]:
            if url and not re.match(r"^https?://", url):
                malformed.append({"id": r["canonical_id"], "field": field, "url": url})
    if malformed:
        issues.append({"type": "malformed_urls", "count": len(malformed), "examples": malformed[:20]})

    return {
        "total": len(records),
        "with_official_website": sum(1 for r in records if r["web"].get("official_website")),
        "with_link_hub": sum(1 for r in records if r["web"].get("link_hub")),
        "with_non_gc_uf_page": sum(
            1 for r in records
            if r["web"].get("uf_page") and is_uf_host(r["web"]["uf_page"]) and not is_gatorconnect(r["web"]["uf_page"])
        ),
        "instagram_high": sum(1 for r in records if (r.get("instagram") or {}).get("confidence") == "HIGH"),
        "instagram_medium": sum(1 for r in records if (r.get("instagram") or {}).get("confidence") == "MEDIUM"),
        "instagram_low": sum(1 for r in records if (r.get("instagram") or {}).get("confidence") == "LOW"),
        "instagram_unresolved": sum(1 for r in records if not (r.get("instagram") or {}).get("handle")),
        "needs_review": sum(1 for r in records if r.get("matching", {}).get("needs_review")),
        "issues": issues,
    }


def write_csv(records, path):
    fields = [
        "canonical_id", "canonical_name", "aliases", "gc_organization_id", "gc_url",
        "categories", "official_website", "uf_page", "link_hub",
        "instagram_handle", "instagram_url", "instagram_confidence", "instagram_match_method",
        "needs_review", "status",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow({
                "canonical_id": r["canonical_id"],
                "canonical_name": r["canonical_name"],
                "aliases": "|".join(r.get("aliases") or []),
                "gc_organization_id": r["gatorconnect"]["organization_id"],
                "gc_url": r["gatorconnect"]["url"],
                "categories": "|".join(r["gatorconnect"].get("category") or []),
                "official_website": r["web"].get("official_website"),
                "uf_page": r["web"].get("uf_page"),
                "link_hub": r["web"].get("link_hub"),
                "instagram_handle": r["instagram"].get("handle"),
                "instagram_url": r["instagram"].get("url"),
                "instagram_confidence": r["instagram"].get("confidence"),
                "instagram_match_method": r["instagram"].get("match_method"),
                "needs_review": r["matching"].get("needs_review"),
                "status": r["gatorconnect"].get("status"),
            })


def main():
    src = RAW / "gatorconnect_details_latest.json"
    if not src.exists():
        raise SystemExit(f"Missing {src}; run 01_fetch_gatorconnect.py first")
    bundles = json.loads(src.read_text(encoding="utf-8"))
    # GatorConnect search can return duplicate Ids; keep first complete detail.
    seen = {}
    for b in bundles:
        sid = None
        if b.get("detail"):
            sid = b["detail"].get("id")
        if sid is None:
            sid = (b.get("search") or {}).get("Id") or (b.get("search") or {}).get("id")
        key = str(sid)
        prev = seen.get(key)
        if prev is None:
            seen[key] = b
        else:
            # prefer entry with detail
            if not prev.get("detail") and b.get("detail"):
                seen[key] = b
    bundles = list(seen.values())

    records = []
    for b in bundles:
        if not b.get("detail"):
            search = b.get("search") or {}
            gc_id = search.get("Id")
            records.append({
                "canonical_id": f"gc-{gc_id}",
                "canonical_name": search.get("Name"),
                "aliases": [search["ShortName"]] if search.get("ShortName") else [],
                "gatorconnect": {
                    "organization_id": str(gc_id),
                    "url": f"{GC_BASE}/organization/{search.get('WebsiteKey') or gc_id}",
                    "website_key": search.get("WebsiteKey"),
                    "category": search.get("CategoryNames") or [],
                    "description": strip_html(search.get("Description")),
                    "summary": strip_html(search.get("Summary")),
                    "status": search.get("Status"),
                    "visibility": search.get("Visibility"),
                    "email": None,
                },
                "web": {
                    "official_website": None,
                    "uf_page": f"{GC_BASE}/organization/{search.get('WebsiteKey') or gc_id}",
                    "link_hub": None,
                },
                "instagram": {"handle": None, "url": None, "confidence": None, "match_method": None, "evidence": []},
                "matching": {"needs_review": True, "notes": f"detail fetch failed: {b.get('error')}"},
                "provenance": [],
                "social_other": {},
            })
            continue
        records.append(build_record(b))

    records.sort(key=lambda r: (r.get("canonical_name") or "").casefold())
    with (DATA / "organizations.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_csv(records, DATA / "organizations.csv")
    summary = validate(records)
    (RAW / "org_validation_pass1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
