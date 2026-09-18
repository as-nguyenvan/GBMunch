#!/usr/bin/env python3
"""Conservative Instagram enrichment from official website / link-hub homepages only."""
from __future__ import annotations

import csv
import json
import re
import ssl
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "raw"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "GatorGrubRegistryBot/0.1 (+UF research; homepage link extraction only)"
IG_RE = re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?", re.I)
SKIP = {"p", "reel", "reels", "stories", "explore", "accounts", "about", "tv", "share", "invites"}
SKIP_HOSTS = {"groupme.com", "chat.whatsapp.com", "discord.gg", "discord.com", "forms.gle", "docs.google.com"}


def fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, context=CTX, timeout=8) as resp:
            return resp.read(250_000).decode("utf-8", errors="ignore")
    except Exception:
        return None


def extract_ig_handles(html: str) -> list[str]:
    handles = []
    for m in IG_RE.finditer(html or ""):
        h = m.group(1).strip(".")
        if h.lower() in SKIP:
            continue
        if h not in handles:
            handles.append(h)
    return handles


def name_token_overlap(org_name: str, handle: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", (org_name or "").lower())
    tokens = [t for t in tokens if len(t) >= 3 and t not in {
        "the", "and", "for", "club", "association", "society", "student", "students",
        "university", "florida", "gators", "gator", "chapter", "at",
    }]
    h = handle.lower().replace(".", "")
    return any(t in h for t in tokens[:6]) if tokens else False


def usable(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return not any(host == h or host.endswith("." + h) for h in SKIP_HOSTS)


def main() -> None:
    path = DATA / "organizations.jsonl"
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    targets = []
    for idx, r in enumerate(records):
        if (r.get("instagram") or {}).get("handle"):
            continue
        urls = [u for u in [r["web"].get("official_website"), r["web"].get("link_hub")] if usable(u)]
        if urls:
            targets.append((idx, urls))

    print(f"targets={len(targets)}", flush=True)
    enriched = ambiguous = checked = failures = 0
    for n, (idx, urls) in enumerate(targets, 1):
        r = records[idx]
        found, evidence = [], []
        for u in urls:
            checked += 1
            html = fetch(u)
            if html is None:
                failures += 1
            else:
                handles = extract_ig_handles(html)
                for h in handles:
                    found.append(h)
                    evidence.append({"source": "official_web_homepage", "url": u, "handle": h})
            time.sleep(0.05)
        found_u = list(dict.fromkeys(found))
        if len(found_u) == 1:
            h = found_u[0]
            overlap = name_token_overlap(r.get("canonical_name") or "", h)
            r["instagram"] = {
                "handle": h,
                "url": f"https://www.instagram.com/{h}/",
                "confidence": "MEDIUM",
                "match_method": "official_website_or_linkhub_homepage",
                "evidence": evidence,
            }
            if not overlap:
                r["matching"]["needs_review"] = True
                note = "IG from website lacks strong name overlap; verify ownership"
                prev = r["matching"].get("notes")
                r["matching"]["notes"] = f"{prev} | {note}" if prev else note
            enriched += 1
        elif len(found_u) > 1:
            ambiguous += 1
            r["matching"]["needs_review"] = True
            note = f"multiple IG links on website: {found_u[:5]}"
            prev = r["matching"].get("notes")
            r["matching"]["notes"] = f"{prev} | {note}" if prev else note
            r["instagram"] = {
                "handle": None, "url": None, "confidence": "LOW",
                "match_method": "official_website_multiple_candidates", "evidence": evidence,
            }
        if n % 25 == 0 or n == len(targets):
            print(f"progress {n}/{len(targets)} enriched={enriched} ambiguous={ambiguous} fail={failures}", flush=True)

    handle_map = defaultdict(list)
    for r in records:
        h = (r.get("instagram") or {}).get("handle")
        if h:
            handle_map[h.casefold()].append(r["canonical_id"])
    for h, ids in handle_map.items():
        uniq = sorted(set(ids))
        if len(uniq) > 1:
            for r in records:
                if ((r.get("instagram") or {}).get("handle") or "").casefold() == h:
                    r["matching"]["needs_review"] = True
                    note = f"shared IG handle {h} across {uniq}"
                    prev = r["matching"].get("notes") or ""
                    if note not in prev:
                        r["matching"]["notes"] = f"{prev} | {note}" if prev else note
                    if r["instagram"].get("confidence") == "MEDIUM":
                        r["instagram"]["confidence"] = "LOW"

    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    fields = [
        "canonical_id", "canonical_name", "aliases", "gc_organization_id", "gc_url",
        "categories", "official_website", "uf_page", "link_hub",
        "instagram_handle", "instagram_url", "instagram_confidence", "instagram_match_method",
        "needs_review", "status",
    ]
    with (DATA / "organizations.csv").open("w", newline="", encoding="utf-8") as f:
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

    summary = {
        "targets": len(targets),
        "checked_pages": checked,
        "fetch_failures": failures,
        "enriched_medium": enriched,
        "ambiguous_multi_ig": ambiguous,
        "instagram_high": sum(1 for r in records if (r.get("instagram") or {}).get("confidence") == "HIGH"),
        "instagram_medium": sum(1 for r in records if (r.get("instagram") or {}).get("confidence") == "MEDIUM"),
        "instagram_low": sum(1 for r in records if (r.get("instagram") or {}).get("confidence") == "LOW"),
        "instagram_unresolved": sum(1 for r in records if not (r.get("instagram") or {}).get("handle")),
        "needs_review": sum(1 for r in records if r.get("matching", {}).get("needs_review")),
        "with_official_website": sum(1 for r in records if r["web"].get("official_website")),
        "total": len(records),
    }
    (RAW / "instagram_web_enrichment_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
