Initial candidate run, before final review
==========================================

The initial installer suite reported 39 failures: 26 were stale current-profile SHA-256 entries in docs/migration-map.json (13 profiles exercised twice). These scoped metadata entries were subsequently refreshed; historical source/migration checksums were preserved. The remaining 13 installer failures and one tools failure match the previously documented baseline failures. The final candidate also corrects gamma-descriptor receiver permissions and restricts the daemon Wayland peer; see the parent directory for the final rerun and compilation evidence.
