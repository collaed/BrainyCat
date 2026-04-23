# BrainyCat — Launch Plan

## Status: Ready for Early Adopters

We have 100+ modules, 220+ routes, 28 MCP tools, 16 enrichment sources, 8 catalog sources. The features are ahead of the infrastructure. Time to find users.

## The Pitch (one sentence)

**"Self-hosted AI reading companion that makes your Calibre library smarter."**

For r/selfhosted: "Like calibre-web but with AI recommendations, audiobook support, and a taste engine."
For r/calibre: "A Calibre plugin that enriches your library continuously and adds a web reader."
For r/audiobooks: "Works with your Audiobookshelf mobile app, adds sleep detection and taste recommendations."

## Target: 10 Early Adopters

### Where to find them

1. **r/selfhosted** — Post when Docker one-liner works cleanly
2. **r/calibre** — Lead with the Calibre plugin
3. **MobileRead forums** — Power users who build Calibre plugins
4. **r/ObsidianMD** — Knowledge workers (annotation export hook)

### What they need to see

- One-command Docker setup that works
- Connect to existing Calibre library (read metadata.db)
- Something useful in 5 minutes (enrichment running, recommendations appearing)
- The 3-tab UI (Library/Discover/Improve) — not 20 pages

### What to listen for

- Which features do they actually use?
- What breaks on their library (edge cases we haven't seen)?
- What's the first thing they ask for that we don't have?
- Do they care about the social features or just the intelligence?

## Before Launch: Checklist

### Must fix
- [ ] Docker one-liner in README (docker compose up -d, visit localhost:8000)
- [ ] First-run setup wizard (create admin user, point to Calibre library or upload)
- [ ] The 3-tab UI (app.html) as the default landing page
- [ ] Secret key generated on first run (not hardcoded)
- [ ] Health check endpoint returns useful info

### Should fix
- [ ] Split web.py into route modules (it's 2600 lines)
- [ ] Error messages that help users fix problems
- [ ] Mobile-responsive CSS (the 3-tab UI works on phones)
- [ ] OPDS tested with Moon+ Reader and KOReader

### Nice to have
- [ ] Demo mode (read-only, pre-loaded library for trying without uploading)
- [ ] Import wizard for Calibre libraries
- [ ] Onboarding tour ("here's what BrainyCat can do")

## The Stack Users Need

```
Minimum:
  docker compose up -d
  → BrainyCat at localhost:8000
  → Upload EPUBs/PDFs, start reading

With Calibre:
  Point BrainyCat at your Calibre library folder
  → Reads metadata.db, shows your books
  → Install Calibre plugin for two-way sync

With Intello:
  Set BRAINYCAT_INTELLO_URL in .env
  → AI summaries, TTS, OCR, auto-tagging unlock

With ABS mobile app:
  Point app at yourserver:8000/compat/abs/
  → Browse and listen on your phone
```

## Competitive Positioning for Each Community

### r/selfhosted
"I built a self-hosted reading companion. It reads your Calibre library, enriches metadata from 16 sources in parallel, generates taste-based recommendations, and has a 28-tool MCP server so Claude can manage your library. Docker one-liner, no cloud dependency."

### r/calibre
"Calibre plugin that continuously enriches your library in the background — 16 metadata sources, ISBN extraction from 9 languages, cover chain (Apple Books + Google Images + Bookcover API), quality scoring. Plus a web reader with night mode and dictionary."

### r/audiobooks
"Works with your Audiobookshelf mobile app (iOS/Android). Adds: smart sleep detection (behavioral dead-man's-switch), taste-based recommendations, reading streaks, book clubs with pace-locked chapters. Your ABS app connects to BrainyCat instead of ABS — same app, more features."

## What Success Looks Like

- 10 users running BrainyCat alongside Calibre
- 3 of them using the Calibre plugin for sync
- 1 feature request we didn't anticipate
- 0 data loss incidents
- Honest feedback on what's useful vs what's noise
