# E2E tests (Playwright)

Requires a running BrainyCat instance and `pip install playwright pytest-playwright && playwright install chromium`.

```bash
BRAINYCAT_E2E_BASE=http://192.168.3.27:8950 \
BRAINYCAT_E2E_USER=admin \
BRAINYCAT_E2E_PASS='<password>' \
pytest tests/e2e/ -v --no-cov
```

Without `BRAINYCAT_E2E_PASS` set, the authenticated test classes skip (they need a real login).
`TestNavigation`/`TestPublicFeed`'s unauthenticated checks still run.

As of 2026-09-26 this suite is fixed to actually run against a real deployment (see git history / the
comment in `test_ui.py`) — a prior version hardcoded an unrelated deployment's URL, prefix, and a
plaintext password, so it had never been executed successfully before. Run it and read the failures as
real signal about what the current UI does and doesn't do, not as an already-passing regression suite.
