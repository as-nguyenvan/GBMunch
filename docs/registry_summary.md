# GatorGrub Registry Summary

**Generated:** 2026-09-17 23:09 UTC  
**Worktree:** `<local-path>`  
**Authoritative org source:** GatorConnect public discovery API (`gatorconnect.ufl.edu`)  
**Gathr:** not used (per project instruction)

## Organization registry

| Metric | Count | Notes |
|---|---:|---|
| Canonical organizations | **977** | Deduped from 1036 GatorConnect search rows (59 API duplicate Ids removed) |
| Official websites | **318** (32.5%) | External non-GatorConnect sites |
| Link hubs (Linktree etc.) | **32** | Stored separately from official websites |
| Instagram HIGH | **148** (15.1%) | Explicit GatorConnect `socialMedia.InstagramUrl` (or ExternalWebsite that is Instagram) |
| Instagram MEDIUM | **98** (10.0%) | Single IG link on official website / link-hub homepage |
| Instagram LOW / ambiguous | **11** | Multiple IG links on homepage; no handle assigned |
| Unresolved / no Instagram handle | **731** (74.8%) | Includes LOW ambiguous |
| Needs review | **47** | Weak name overlap, multi-candidate pages, etc. |

### Trust posture

- **Optimize for trustworthiness, not match rate.** HIGH coverage at ~15% is expected and preferred over aggressive fuzzy matching.
- No fuzzy username search was used for verified matches.
- No shared Instagram handle across distinct canonical orgs after validation.
- MEDIUM matches are **candidates**, not verified ownership. Several lack UF/Florida/gator tokens in the handle and/or strong name overlap.

### Suspicious / ambiguous MEDIUM examples (manual review recommended)

- Accent A Cappella → `@nsaccent` (needs_review=False)
- American Pharmacists Association Academy of Student Pharmacists, Gainesville Campus → `@aphapharmacists` (needs_review=False)
- Best Buddies → `@friendshipwalk` (needs_review=True)
- Canvas College → `@canvas_fl` (needs_review=False)
- CHOMP Partners → `@chompprivateequity` (needs_review=False)
- ChomPics Productions → `@chompicsproductions` (needs_review=False)
- Christian Pharmacists Fellowship International → `@christianpharmacistsfi` (needs_review=False)
- Club Golf → `@nccga` (needs_review=True)
- DELTA DELTA DELTA → `@tridelta` (needs_review=False)
- Flipping the System → `@flippingthesystem` (needs_review=False)
- Food Recovery Network → `@foodrecovery` (needs_review=False)
- Girls Who Code at Gainesville → `@girlswhocode` (needs_review=False)
- Global Medical Brigades → `@medicalbrigades` (needs_review=False)
- Humanity First Student Organization → `@hfstudentdiv` (needs_review=True)
- Kappa Psi - Epsilon Mu - Orlando → `@epsilonmu.kappapsi` (needs_review=False)


### HIGH examples (good)

- 3D Printing Club → `@3dprintUF` via `gatorconnect_explicit_link`
- Academic Allies → `@ufacademicallies` via `gatorconnect_explicit_link`
- Academy of Managed Care Pharmacy → `@ufamcpgnv` via `gatorconnect_explicit_link`
- Ad Society → `@ufadsociety` via `gatorconnect_explicit_link`
- ALPHA CHI OMEGA → `@ufaxo` via `gatorconnect_explicit_link`
- Alpha Chi Sigma - Beta Iota Chapter → `@alphachisigmauf` via `gatorconnect_explicit_link`
- ALPHA DELTA PI → `@adpiuf` via `gatorconnect_explicit_link`
- Alpha Epsilon Delta → `@ufaed` via `gatorconnect_explicit_link`


### Unresolved examples (no Instagram)

- 180 Degrees Consulting at UF (website=none)
- A Private Inn (website=https://groupme.com/join_group/91848249/1N2kgEhF)
- Academy of Managed Care Pharmacy - Orlando Campus (website=none)
- ACS Cancer Action Network at UF (website=none)
- Advanced Professional Degree Consulting Club (website=https://apdccufl.com)
- Adventist Christian Fellowship (website=none)
- AeroGator (website=none)
- Afaq Cultural Society (website=none)


### Top GatorConnect categories

- Academic: 463
- Social: 462
- Service: 340
- Special Interest: 338
- Professional: 325
- Cultural: 190
- Engineering & Technology: 109
- Athletic: 94
- Social Sorority/Fraternity (RSO SSF): 55
- Religious/Spiritual : 49
- Political: 46
- Virtual Offerings: 30


## Event-source registry

| Metric | Count |
|---|---:|
| Event sources | **30** |
| Reachable in validation fetch | **29** |
| Food-signal observed on landing page | **8** |

### By priority

- high: 10
- low: 4
- medium: 16

### By type

- college_calendar: 10
- student_affairs: 2
- cultural_center: 2
- central_calendar: 1
- programming: 1
- orientation: 1
- venue_programming: 1
- student_government: 1
- career: 1
- career_platform: 1
- libraries: 1
- org_platform_events: 1
- graduate: 1
- institute: 1
- community_forum: 1
- aggregator: 1
- news: 1
- recreation: 1
- museum: 1

### Highest-value categories for next acquisition

1. **GatorConnect Events** + org Instagram (once HIGH/MEDIUM handles trusted) — highest density of RSO free-food posts
2. **GatorNights / Reitz Union programming** — recurring campus-wide free food signals already observed
3. **College calendars** (Engineering, Warrington, CLAS, PHHP) — structured/semi-structured listings
4. **Career Connections / Welcome** — periodic high-volume food events
5. **Community** (r/ufl, Eventbrite) — noisy; use only as leads, never as canonical truth

### Sources with observed food-language signals

- [high] GatorNights — https://union.ufl.edu/gatornights/
- [medium] Great Gator Welcome — https://welcome.ufl.edu/
- [high] Reitz Union — https://union.ufl.edu/
- [high] Herbert Wertheim College of Engineering Events — https://www.eng.ufl.edu/students/events/
- [high] Warrington College of Business Events — https://warrington.ufl.edu/events/
- [medium] PHHP Events — https://phhp.ufl.edu/
- [low] College of Journalism Events — https://www.jou.ufl.edu/
- [low] Eventbrite UF search — https://www.eventbrite.com/d/fl--gainesville/university-of-florida/

### Access obstacles

- `uf-main-calendar` https://calendar.ufl.edu/ — calendar.ufl.edu returns 403 to automated clients; treat as high-value but access-constrained. Manual/browser or official feed may be required.


## Method notes

### Organization acquisition
- Listing: `GET https://gatorconnect.ufl.edu/api/discovery/search/organizations?top=100&skip=N`
- Detail: `GET https://gatorconnect.ufl.edu/api/discovery/organization/{id}`
- Public, unauthenticated, JSON; no HTML scraping of the directory.
- GatorConnect search returned **1036 rows / 977 unique Ids** — builder dedupes by Id.

### Instagram discovery order honored
1. Explicit GatorConnect social link → HIGH
2. Official website / UF page / link-hub homepage link → MEDIUM (single handle only)
3. Fuzzy/name search → **not used** for assignment

### Validation checks run
- Duplicate canonical IDs (fixed via dedupe)
- Duplicate names caused by API dupes (cleared after dedupe)
- Shared Instagram handles across orgs (none)
- Malformed URLs (none)
- Empty names (none)

## Files created

```
data/organizations.jsonl
data/organizations.csv
data/event_sources.jsonl
data/event_sources.csv
reports/registry_summary.md
scripts/01_fetch_gatorconnect.py
scripts/02_build_org_registry.py
scripts/03_build_event_sources.py
scripts/04_enrich_instagram_from_web.py
raw/gatorconnect_details_latest.json
```

## Recommended next acquisition step

1. Human-spot-check the **47 needs_review** org rows (especially MEDIUM without UF tokens).
2. Prefer **HIGH Instagram** + **GatorConnect Events** + **GatorNights/Union** as the first live event-acquisition adapters.
3. Do **not** scrape Instagram posts yet until MEDIUM review queue is acceptable.
4. Resolve `calendar.ufl.edu` access (browser feed / official ICS if available) before depending on it.
5. Keep Hermes backend untouched until org `canonical_id` (`gc-{id}`) is wired as a foreign key into `FoodEvent` provenance.
