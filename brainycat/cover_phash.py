"""Cover perceptual hashing — NOT YET IMPLEMENTED (planned: dedup D2, requires imagehash/Pillow).

Intentionally raises so it can never report success for work it didn't do (CLAUDE.md convention). It
is not scheduled in `brainycat/scheduler.py` while it's a stub; when implemented, give it a real body
(perceptual-hash each cover, store the hash, feed the dedup fused scorer) and re-add its loop.
"""


async def process_batch(batch_size: int = 20) -> dict:
    raise NotImplementedError("cover_phash.process_batch is a stub — see docs/roadmap/dedup-overhaul.md (D2)")
