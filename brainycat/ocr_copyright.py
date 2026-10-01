"""OCR copyright-page ISBN extraction — NOT YET IMPLEMENTED (planned: requires Intello OCR).

Raises rather than returning a zero-count "success", so a scheduled loop or the M10 heartbeat can't
show it green while it does nothing (CLAUDE.md convention). Not scheduled while it's a stub.
"""


async def process_batch(batch_size: int = 5) -> dict:
    raise NotImplementedError("ocr_copyright.process_batch is a stub — needs Intello OCR")
