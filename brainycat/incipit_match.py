"""Incipit (opening-text) duplicate matching — NOT YET IMPLEMENTED.

The real extraction helpers live in `brainycat/incipit.py`; this module (the batch matcher the
scheduler would call) is still a stub. It raises rather than returning a zero-count "success", so it
can't show green while doing nothing (CLAUDE.md convention). Not scheduled while it's a stub.
"""


async def find_incipit_matches(batch_size: int = 100) -> dict:
    raise NotImplementedError("incipit_match.find_incipit_matches is a stub — build on brainycat/incipit.py")
