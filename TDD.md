# TDD execution record

Each behavior slice was introduced by a focused test and run before production code. Observed RED causes, in order:

1. Domain contracts: `ModuleNotFoundError: gatorgrub`
2. Adapters/extraction: missing `gatorgrub.extraction.extractor`
3. Verification: missing `gatorgrub.verification.verifier`
4. Deduplication: missing `gatorgrub.deduplication.matcher`
5. Recommendation: missing ranker; first implementation then exposed the too-short explicit-free pattern before GREEN
6. Repository: missing `gatorgrub.storage.repository`
7. API: missing `gatorgrub.api.app`
8. Offline demo: missing `gatorgrub.demo`; first implementation exposed over-broad same-day deduplication
9. Stale-source regression: expected review but got trusted
10. Future-adapter integration: missing `gatorgrub.pipeline`

Each slice was implemented minimally, rerun to green, then followed by the full suite. `pytest -q` is the final regression command.
