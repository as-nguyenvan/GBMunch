#!/usr/bin/env python3
"""Build and lightly validate UF public event-source registry (no event scraping)."""
from __future__ import annotations

import csv
import json
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "raw"
DATA.mkdir(parents=True, exist_ok=True)

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE

UA = "GatorGrubRegistryBot/0.1 (+UF research; source-registry validation only)"

FOOD_PATTERNS = [
    r"free\s+food", r"free\s+pizza", r"food\s+provided", r"refreshments",
    r"lunch\s+provided", r"dinner\s+provided", r"breakfast", r"\bcoffee\b",
    r"pastries", r"\bsnacks?\b", r"\bcatered\b", r"chick-?fil-?a", r"\bpublix\b",
    r"\bpizza\b", r"while\s+supplies\s+last", r"free\s+lunch", r"free\s+dinner",
]


def fetch(url: str, timeout: int = 25) -> tuple[int | None, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as resp:
            body = resp.read(500_000).decode("utf-8", errors="ignore")
            return resp.status, body
    except Exception as e:
        return None, str(e)


def food_signal(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in FOOD_PATTERNS)


SEED = [
  # CENTRAL
  {"source_id":"uf-main-calendar","name":"UF Main Calendar","base_url":"https://calendar.ufl.edu/","source_type":"central_calendar","scope":"campus_wide","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Central UF events calendar"},
  {"source_id":"uf-student-engagement","name":"UF Student Engagement","base_url":"https://studentengagement.ufl.edu/","source_type":"student_affairs","scope":"campus_wide","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Student Engagement home / programs"},
  {"source_id":"uf-gatornights","name":"GatorNights","base_url":"https://union.ufl.edu/gatornights/","source_type":"programming","scope":"campus_wide","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Weekend late-night programming; frequent free food"},
  {"source_id":"uf-great-gator-welcome","name":"Great Gator Welcome","base_url":"https://welcome.ufl.edu/","source_type":"orientation","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Welcome week / new student events (seasonal)"},
  {"source_id":"uf-reitz-union","name":"Reitz Union","base_url":"https://union.ufl.edu/","source_type":"venue_programming","scope":"campus_wide","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Union events and programs"},
  {"source_id":"uf-student-government","name":"UF Student Government","base_url":"https://sg.ufl.edu/","source_type":"student_government","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"SG events and announcements"},
  {"source_id":"uf-career-connections","name":"Career Connections Center","base_url":"https://career.ufl.edu/","source_type":"career","scope":"campus_wide","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Career events; often food at workshops/fairs"},
  {"source_id":"uf-careerhub","name":"Handshake / CareerHub","base_url":"https://ufl.joinhandshake.com/","source_type":"career_platform","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":True,"requires_auth":True,"notes":"May require login for full event lists"},
  {"source_id":"uf-libraries","name":"UF Libraries Events","base_url":"https://uflib.ufl.edu/","source_type":"libraries","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Library workshops and events"},
  {"source_id":"uf-sfl","name":"Sorority & Fraternity Life","base_url":"https://www.ufsa.ufl.edu/","source_type":"greek_life","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"SFL office; chapter events more often on org pages/IG"},
  {"source_id":"gatorconnect-events","name":"GatorConnect Events","base_url":"https://gatorconnect.ufl.edu/events","source_type":"org_platform_events","scope":"campus_wide","authority":"official_uf","priority":"high","access_method":"html","structured":True,"requires_auth":False,"notes":"Platform event listings for registered orgs; listing pages may require soft login"},
  # COLLEGE / DEPT
  {"source_id":"eng-calendar","name":"Herbert Wertheim College of Engineering Events","base_url":"https://www.eng.ufl.edu/students/events/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Engineering college events"},
  {"source_id":"clas-news-events","name":"CLAS News & Events","base_url":"https://clas.ufl.edu/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"College of Liberal Arts & Sciences"},
  {"source_id":"warrington-events","name":"Warrington College of Business Events","base_url":"https://warrington.ufl.edu/events/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Business college events"},
  {"source_id":"arts-events","name":"College of the Arts Events","base_url":"https://arts.ufl.edu/events/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Arts performances and events"},
  {"source_id":"honors-events","name":"UF Honors Events","base_url":"https://www.honors.ufl.edu/","source_type":"college_calendar","scope":"program","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Honors program site; events often listed on pages/news"},
  {"source_id":"multicultural-engagement","name":"Multicultural & Diversity Affairs / IIC","base_url":"https://multicultural.ufl.edu/","source_type":"cultural_center","scope":"campus_wide","authority":"official_uf","priority":"high","access_method":"html","structured":False,"requires_auth":False,"notes":"Cultural center programming"},
  {"source_id":"graduate-school-events","name":"UF Graduate School Events","base_url":"https://grad.ufl.edu/","source_type":"graduate","scope":"graduate","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Graduate events"},
  {"source_id":"ifas-events","name":"UF/IFAS Events","base_url":"https://calendar.ifas.ufl.edu/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"IFAS calendar"},
  {"source_id":"phhp-events","name":"PHHP Events","base_url":"https://phhp.ufl.edu/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Public Health & Health Professions"},
  {"source_id":"journalism-events","name":"College of Journalism Events","base_url":"https://www.jou.ufl.edu/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"low","access_method":"html","structured":False,"requires_auth":False,"notes":"CJC homepage/events"},
  {"source_id":"education-events","name":"College of Education Events","base_url":"https://education.ufl.edu/events/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Education college"},
  {"source_id":"hhp-events","name":"Health & Human Performance Events","base_url":"https://hhp.ufl.edu/","source_type":"college_calendar","scope":"college","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"HHP"},
  {"source_id":"cpet-events","name":"Center for Undergraduate Research","base_url":"https://cur.aa.ufl.edu/","source_type":"institute","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Undergraduate research events"},
  {"source_id":"uf-icdc","name":"International Center","base_url":"https://internationalcenter.ufl.edu/","source_type":"cultural_center","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"International student programming"},
  # COMMUNITY / DISCOVERY
  {"source_id":"reddit-ufl","name":"r/ufl","base_url":"https://www.reddit.com/r/ufl/","source_type":"community_forum","scope":"campus_wide","authority":"community","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Community tips; noisy; verify before trusting food claims"},
  {"source_id":"eventbrite-uf","name":"Eventbrite UF search","base_url":"https://www.eventbrite.com/d/fl--gainesville/university-of-florida/","source_type":"aggregator","scope":"local","authority":"community","priority":"low","access_method":"html","structured":True,"requires_auth":False,"notes":"Public Eventbrite listings near UF; filter carefully"},
  {"source_id":"uf-news","name":"UF News Events","base_url":"https://news.ufl.edu/","source_type":"news","scope":"campus_wide","authority":"official_uf","priority":"low","access_method":"html","structured":False,"requires_auth":False,"notes":"Newsroom; occasional event coverage"},
  {"source_id":"recsports","name":"UF RecSports","base_url":"https://recsports.ufl.edu/","source_type":"recreation","scope":"campus_wide","authority":"official_uf","priority":"medium","access_method":"html","structured":False,"requires_auth":False,"notes":"Recreation events; occasional free food"},
  {"source_id":"uf-museum-natural-history","name":"Florida Museum Events","base_url":"https://www.floridamuseum.ufl.edu/events/","source_type":"museum","scope":"campus_adjacent","authority":"official_uf","priority":"low","access_method":"html","structured":False,"requires_auth":False,"notes":"Museum public events"},
]


def main():
    rows = []
    obstacles = []
    for seed in SEED:
        status, body = fetch(seed["base_url"])
        reachable = status is not None and status < 400
        signal = bool(reachable and food_signal(body))
        rec = dict(seed)
        rec["reachable"] = reachable
        rec["http_status"] = status
        rec["food_signal_observed"] = signal
        rec["validated_at"] = datetime.now(timezone.utc).isoformat()
        if not reachable:
            obstacles.append({"source_id": seed["source_id"], "url": seed["base_url"], "error": body[:300]})
            rec["notes"] = (rec.get("notes") or "") + f" | access obstacle: {body[:120]}"
        rows.append(rec)
        print(f"{seed['source_id']}: status={status} food={signal}", flush=True)
        time.sleep(0.2)

    out_jsonl = DATA / "event_sources.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    fields = [
        "source_id","name","base_url","source_type","scope","authority","priority",
        "access_method","structured","requires_auth","food_signal_observed","reachable","http_status","notes"
    ]
    with (DATA / "event_sources.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    summary = {
        "total": len(rows),
        "reachable": sum(1 for r in rows if r.get("reachable")),
        "food_signal_observed": sum(1 for r in rows if r.get("food_signal_observed")),
        "by_priority": {},
        "by_type": {},
        "obstacles": obstacles,
    }
    for r in rows:
        summary["by_priority"][r["priority"]] = summary["by_priority"].get(r["priority"], 0) + 1
        summary["by_type"][r["source_type"]] = summary["by_type"].get(r["source_type"], 0) + 1
    (RAW / "event_sources_validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
