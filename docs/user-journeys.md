# BrainyCat — User Journeys

## UJ-01: First Visit & Authentication
1. User navigates to `your-server:8000`
2. Caddy forward_auth redirects to ECB login page
3. User enters credentials (admin / password)
4. Redirect back to `/brainycat/` → 307 → `/brainycat/static/index.html`
5. Library UI loads with empty state: "No books yet. Upload or import from the catalog!"
6. `GET /api/v1/me` returns `{"user": {"username": "admin", "role": "admin"}}`

## UJ-02: Upload an Ebook
1. User drags an EPUB file onto the drop zone (or clicks Upload button)
2. `POST /api/v1/books/upload` with multipart file
3. Backend extracts metadata (title, author, cover, language, ISBN) from EPUB
4. Book appears in the library grid with cover art, title, author, format badge "epub"
5. `GET /api/v1/books` returns the new book in the list

## UJ-03: Upload an Audiobook
1. User uploads an M4B or MP3 file
2. Backend extracts audio metadata (title, artist, duration, bitrate, chapters)
3. Book appears with format badge "m4b" or "mp3"
4. Duration and chapter count shown in book detail

## UJ-04: Browse & Search Library
1. User types in the search box → real-time filtering via `GET /api/v1/books?q=...`
2. Full-text search (tsvector) + fuzzy matching (pg_trgm) find results
3. User filters by format dropdown (epub, mp3, m4b)
4. User sorts by title, recent, or quality score
5. Keyboard shortcut `/` focuses search, `j`/`k` would navigate (future)

## UJ-05: View Book Details
1. User clicks a book card → modal opens with full metadata
2. Shows: title, author, description, quality score, ISBN, formats, linked books
3. Action buttons: Read, Listen, Bilingual, Enrich, Kindle, → Audio

## UJ-06: Read an Ebook (EPUB Reader)
1. User clicks "📖 Read" on an EPUB book
2. `reader.html` loads with EPUB.js rendering the book
3. Previous reading position restored via `GET /api/v1/progress/{book_id}`
4. User reads, turns pages with arrow keys or swipe
5. Progress saved automatically every 5 seconds via `PUT /api/v1/progress/{book_id}`
6. TOC sidebar available via ☰ button
7. Font size adjustable with A-/A+ buttons
8. Theme switchable: dark/light/sepia
9. User closes tab → reopens later → exact position restored

## UJ-07: Listen to an Audiobook (Audio Player)
1. User clicks "🎧 Listen" on an audiobook
2. `player.html` loads with custom audio player
3. Previous listening position restored via `GET /api/v1/progress/{book_id}`
4. Controls: play/pause, ±15s/±30s skip, chapter navigation, speed (0.5x–3x)
5. Sleep timer available
6. Progress saved every 10 seconds via `PUT /api/v1/progress/{book_id}`
7. Mobile lock screen controls via Media Session API
8. Multi-file audiobooks: chapters listed, auto-advance to next file

## UJ-08: Switch Between Reading and Listening (Sync)
1. User is reading an ebook at chapter 3, paragraph 5
2. Clicks "🎧 Audio" button in the reader toolbar
3. `GET /api/v1/sync/position/{book_id}?from=text&position=...` translates position
4. Audio player opens at the corresponding timestamp
5. Reverse: listening → clicks "📖 Text" → reader opens at matching text position

## UJ-09: Enrich Book Metadata
1. User clicks "✨ Enrich" on a book with sparse metadata
2. `POST /api/v1/books/{id}/enrich` queries Google Books, Open Library, Gutendex
3. Description, cover art, ISBN, genres auto-populated
4. Quality score jumps (e.g., 20 → 85)
5. Book card in library updates with new cover and metadata

## UJ-10: Import from Project Gutenberg
1. User navigates to Catalog page (`catalog.html`)
2. Searches "Pride and Prejudice" → `GET /api/v1/catalog/gutenberg/search?q=...`
3. Results show with title, author, download count
4. User clicks "📥 Import" → `POST /api/v1/catalog/gutenberg/{id}/import`
5. EPUB downloaded from Gutenberg, book created in library with metadata
6. Book appears in library grid

## UJ-11: Browse LibriVox Audiobooks
1. User switches to LibriVox tab on Catalog page
2. Searches by title → `GET /api/v1/catalog/librivox/search?title=...`
3. Results show with title, authors, total time, number of sections
4. Link to listen on LibriVox provided

## UJ-12: Send Book to Kindle
1. User sets Kindle email in preferences: `PATCH /api/v1/me/preferences` with `kindle_email`
2. Opens a book → clicks "📱 Kindle"
3. `POST /api/v1/books/{id}/send-to-kindle` converts to EPUB if needed, emails via SMTP
4. Book arrives on Kindle device within minutes

## UJ-13: Convert Ebook to Audiobook (TTS)
1. User clicks "🔊 → Audio" on an ebook
2. `POST /api/v1/books/{id}/convert/tts?voice=en_US-lessac-medium`
3. Background job created, returns job ID
4. `GET /api/v1/jobs/{id}` polled for progress (0% → 100%)
5. Piper TTS generates audio per chapter, combines into M4B
6. New audiobook file linked to the same book
7. User can now listen to the generated audiobook

## UJ-14: Transcribe Audiobook to Ebook (STT)
1. User clicks equivalent STT action on an audiobook
2. `POST /api/v1/books/{id}/convert/stt?model=small`
3. faster-whisper transcribes with word-level timestamps
4. EPUB generated with chapter structure
5. Sync map stored for text↔audio position mapping (UJ-08)

## UJ-15: Convert Ebook Format
1. User needs MOBI version → `POST /api/v1/books/{id}/convert/mobi`
2. Calibre CLI converts EPUB → MOBI
3. New file added to the book's file list

## UJ-16: Translate a Book
1. User opens a French book → clicks "Translate"
2. Selects target language (English) and backend (Argos/local)
3. `POST /api/v1/books/{id}/translate?target_lang=en&backend=argos`
4. Background job translates paragraph by paragraph
5. New translated EPUB created, linked to original as "translation"
6. Both versions available in library

## UJ-17: Read in Bilingual Mode
1. User opens a book that has a translation linked
2. Clicks "🌐 Bilingual" → `bilingual.html` loads
3. Left column: original text; Right column: translation
4. Columns scroll in sync
5. Click a paragraph → counterpart highlighted
6. Click a word → translation popup via LLM

## UJ-18: Audio Restoration
1. User uploads an old LibriVox recording with tape hiss
2. Clicks "Diagnose" → `POST /api/v1/books/{id}/audio/diagnose`
3. Report shows: hiss_score: 72, crackle_score: 15, recommended: "tape"
4. Clicks "Preview (tape)" → `POST /api/v1/books/{id}/audio/preview?profile=tape`
5. Listens to 30-second cleaned sample
6. Clicks "Apply" → `POST /api/v1/books/{id}/audio/restore?profile=tape`
7. Full restoration runs as background job
8. Original file preserved, restored version added as new file

## UJ-19: Incoming Folder Scanner
1. Admin drops files into `/data/incoming/` folder
2. Scanner detects new files, parses filenames ("Author - Title.epub")
3. `GET /api/v1/incoming` shows pending items with proposed metadata
4. User reviews on `incoming.html` page
5. Clicks "✓ Confirm" → file moved to library, book record created
6. Or clicks "✕ Reject" → item marked as rejected

## UJ-20: Library Intelligence
1. User navigates to Intelligence page (`intelligence.html`)
2. Quality Issues: books with low bitrate, missing chapters flagged
3. Series Gaps: "Harry Potter — owned: 1,2,4 — missing: 3"
4. Duplicates: "The Hobbit ↔ The Hobbit (Illustrated)" at 85% similarity

## UJ-21: Collections & Shelves
1. User creates collection "Summer Reading" → `POST /api/v1/collections`
2. Adds books to it → `POST /api/v1/collections/{id}/books/{book_id}`
3. Reorders books within collection
4. Default collections auto-created: "Currently Reading", "Want to Read", "Finished"

## UJ-22: Book Linking
1. User has an ebook and audiobook of the same title
2. Links them → `POST /api/v1/books/{id}/link` with `link_type: "ebook_audiobook"`
3. Book detail shows linked versions
4. "Switch to Audio" / "Switch to Text" buttons appear in reader/player

## UJ-23: Recommendations
1. User navigates to Recommendations page (`recommendations.html`)
2. Profile built from finished books → `GET /api/v1/recommendations/profile`
3. Five categories displayed:
   - DNA Match: semantically similar to taste profile
   - Authors You Love: more from favorite authors
   - Complete Series: next book in unfinished series
   - Hidden Gems: high-quality, low-popularity matches
4. Click a recommendation → opens in reader

## UJ-24: AI Book Companion
1. User is reading a novel, wants a recap
2. `GET /api/v1/ai/recap/{book_id}` → LLM summarizes content up to current position
3. No spoilers: only content before the reader's progress percentage is used
4. User asks "Who is character X?" → `POST /api/v1/ai/ask/{book_id}?question=...`
5. Auto-tagging: `POST /api/v1/ai/auto-tag/{book_id}` → genres, mood, themes, pace

## UJ-25: Reviews & Ratings
1. User opens book detail → reviews section
2. `GET /api/v1/books/{id}/reviews` fetches from Google Books + Open Library
3. Shows weighted average rating (e.g., 4.2/5) with per-source breakdown
4. Cached for 24 hours

## UJ-26: Reading Statistics
1. User navigates to Stats page (`stats.html`)
2. Dashboard shows: total books finished, current reading streak
3. Bar chart: books per month
4. Doughnut chart: genre distribution
5. Data from `GET /api/v1/stats/overview`

## UJ-27: Book Notes & Journal
1. User opens a book → writes markdown notes
2. `POST /api/v1/books/{id}/notes` saves content
3. Notes persisted per user per book
4. `GET /api/v1/notes/export` exports all notes as JSON

## UJ-28: OPDS Feed
1. User adds `your-server:8000/api/v1/opds/catalog.xml` to Moon+ Reader
2. OPDS 1.2 feed lists all books with covers and download links
3. Search via OPDS: `GET /api/v1/opds/search?q=...`

## UJ-29: Podcast Feed
1. User creates a drip-schedule feed for an audiobook
2. `POST /api/v1/books/{id}/podcast-feed?schedule=daily`
3. Subscribes to RSS URL in podcast app
4. One chapter released per day at 08:00

## UJ-30: Import Existing Libraries
1. Admin imports from audiobookshelf: `POST /api/v1/import/audiobookshelf`
2. Reads `/opt/audiobookshelf/config/absdatabase.sqlite`
3. Books, metadata, and progress migrated
4. Goodreads CSV import: upload CSV → books + ratings imported
5. Calibre import: point to metadata.db + book files directory

## UJ-31: Multi-User
1. Three users: admin, reader1, reader2
2. Each has own reading progress, bookmarks, annotations, collections
3. All share the same book files (no duplication)
4. Admin can manage users via `GET /api/v1/users`, `PATCH /api/v1/users/{id}`

## UJ-32: Signal Notifications
1. When a book is added or a job completes, Signal notification sent
2. Via `signal-api:8080` REST endpoint

## UJ-33: CLI Tool
1. `brainycat upload book.epub` → uploads via API
2. `brainycat search "gatsby"` → searches library
3. `brainycat send-to-kindle <id>` → sends to Kindle
4. `brainycat stats` → shows reading statistics
5. `brainycat health` → checks server status
