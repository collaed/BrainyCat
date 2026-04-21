"""initial schema

Revision ID: 001
Revises: None
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector — requires pgvector/pgvector image; skip gracefully if unavailable
    op.execute("""
    DO $$ BEGIN
        CREATE EXTENSION IF NOT EXISTS vector;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'pgvector not available — vector columns will be added later';
    END $$;
    """)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    op.execute("""
    -- ============================================================
    -- USERS
    -- ============================================================
    CREATE TABLE users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT,
        email TEXT,
        kindle_email TEXT,
        role TEXT NOT NULL DEFAULT 'reader' CHECK (role IN ('admin', 'reader')),
        oauth_accounts JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE user_preferences (
        user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        theme TEXT DEFAULT 'dark',
        font_size INTEGER DEFAULT 16,
        font_family TEXT DEFAULT 'system-ui',
        fluent_languages TEXT[] DEFAULT '{}',
        secondary_languages TEXT[] DEFAULT '{}',
        preferred_format TEXT DEFAULT 'ebook',
        reading_settings JSONB DEFAULT '{}',
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    -- ============================================================
    -- BOOKS (Calibre-inspired normalized schema)
    -- ============================================================
    CREATE TABLE books (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title TEXT NOT NULL DEFAULT 'Unknown' COLLATE "und-x-icu",
        sort_title TEXT COLLATE "und-x-icu",
        isbn TEXT,
        description TEXT,
        cover_path TEXT,
        quality_score INTEGER DEFAULT 0 CHECK (quality_score BETWEEN 0 AND 100),
        pubdate TIMESTAMPTZ,
        series_index REAL DEFAULT 1.0,
        extra_metadata JSONB DEFAULT '{}',
        search_vector tsvector,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    -- Vector columns added conditionally
    DO $$ BEGIN
        ALTER TABLE books ADD COLUMN embedding vector(384);
    EXCEPTION WHEN undefined_object THEN
        RAISE NOTICE 'vector type not available — skipping embedding column';
    END $$;

    CREATE INDEX books_search_idx ON books USING gin(search_vector);
    CREATE INDEX books_title_trgm_idx ON books USING gin(title gin_trgm_ops);
    CREATE INDEX books_isbn_idx ON books(isbn) WHERE isbn IS NOT NULL;
    CREATE INDEX books_quality_idx ON books(quality_score);

    DO $$ BEGIN
        CREATE INDEX books_embedding_idx ON books USING ivfflat(embedding vector_cosine_ops) WITH (lists = 50);
    EXCEPTION WHEN undefined_object THEN
        RAISE NOTICE 'vector type not available — skipping embedding index';
    END $$;

    CREATE TABLE authors (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL UNIQUE COLLATE "und-x-icu",
        sort_name TEXT COLLATE "und-x-icu",
        link TEXT DEFAULT ''
    );
    CREATE INDEX authors_name_trgm_idx ON authors USING gin(name gin_trgm_ops);

    CREATE TABLE tags (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL UNIQUE COLLATE "und-x-icu"
    );

    CREATE TABLE series (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL UNIQUE COLLATE "und-x-icu",
        sort_name TEXT COLLATE "und-x-icu"
    );

    CREATE TABLE publishers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL UNIQUE COLLATE "und-x-icu"
    );

    CREATE TABLE languages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        code TEXT NOT NULL UNIQUE,
        name TEXT
    );

    -- M:N link tables
    CREATE TABLE books_authors (
        book_id UUID REFERENCES books(id) ON DELETE CASCADE,
        author_id UUID REFERENCES authors(id) ON DELETE CASCADE,
        PRIMARY KEY (book_id, author_id)
    );

    CREATE TABLE books_tags (
        book_id UUID REFERENCES books(id) ON DELETE CASCADE,
        tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (book_id, tag_id)
    );

    CREATE TABLE books_series (
        book_id UUID REFERENCES books(id) ON DELETE CASCADE,
        series_id UUID REFERENCES series(id) ON DELETE CASCADE,
        PRIMARY KEY (book_id, series_id)
    );

    CREATE TABLE books_publishers (
        book_id UUID REFERENCES books(id) ON DELETE CASCADE,
        publisher_id UUID REFERENCES publishers(id) ON DELETE CASCADE,
        PRIMARY KEY (book_id, publisher_id)
    );

    CREATE TABLE books_languages (
        book_id UUID REFERENCES books(id) ON DELETE CASCADE,
        language_id UUID REFERENCES languages(id) ON DELETE CASCADE,
        item_order INTEGER DEFAULT 0,
        PRIMARY KEY (book_id, language_id)
    );

    -- ============================================================
    -- BOOK FILES
    -- ============================================================
    CREATE TABLE book_files (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        format TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_size BIGINT DEFAULT 0,
        mime_type TEXT,
        bitrate INTEGER,
        duration_seconds REAL,
        has_chapters BOOLEAN DEFAULT false,
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX book_files_book_idx ON book_files(book_id);

    CREATE TABLE audio_chapters (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        file_id UUID NOT NULL REFERENCES book_files(id) ON DELETE CASCADE,
        chapter_index INTEGER NOT NULL,
        title TEXT,
        start_time REAL NOT NULL,
        end_time REAL NOT NULL,
        UNIQUE (file_id, chapter_index)
    );

    -- ============================================================
    -- READING PROGRESS, BOOKMARKS, ANNOTATIONS
    -- ============================================================
    CREATE TABLE reading_progress (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        file_id UUID REFERENCES book_files(id) ON DELETE SET NULL,
        position TEXT,
        position_timestamp REAL,
        percentage REAL DEFAULT 0,
        is_finished BOOLEAN DEFAULT false,
        updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (user_id, book_id)
    );

    CREATE TABLE bookmarks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        position TEXT NOT NULL,
        title TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX bookmarks_user_book_idx ON bookmarks(user_id, book_id);

    CREATE TABLE annotations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        cfi_range TEXT NOT NULL,
        text_content TEXT,
        note TEXT,
        color TEXT DEFAULT '#ffeb3b',
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX annotations_user_book_idx ON annotations(user_id, book_id);

    -- ============================================================
    -- BOOK NOTES (journal)
    -- ============================================================
    CREATE TABLE book_notes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        content TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (user_id, book_id)
    );

    -- ============================================================
    -- COLLECTIONS
    -- ============================================================
    CREATE TABLE collections (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        is_public BOOLEAN DEFAULT false,
        is_default BOOLEAN DEFAULT false,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX collections_user_idx ON collections(user_id);

    CREATE TABLE collection_books (
        collection_id UUID REFERENCES collections(id) ON DELETE CASCADE,
        book_id UUID REFERENCES books(id) ON DELETE CASCADE,
        position INTEGER DEFAULT 0,
        added_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (collection_id, book_id)
    );

    -- ============================================================
    -- BOOK LINKS (ebook↔audiobook, original↔translation)
    -- ============================================================
    CREATE TABLE book_links (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_a_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        book_b_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        link_type TEXT NOT NULL CHECK (link_type IN ('ebook_audiobook', 'translation', 'edition')),
        created_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (book_a_id, book_b_id, link_type)
    );

    -- ============================================================
    -- TRANSLATIONS
    -- ============================================================
    CREATE TABLE book_translations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        target_book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        source_language TEXT NOT NULL,
        target_language TEXT NOT NULL,
        backend TEXT NOT NULL,
        paragraph_map JSONB DEFAULT '[]',
        created_at TIMESTAMPTZ DEFAULT now()
    );

    -- ============================================================
    -- REVIEWS CACHE
    -- ============================================================
    CREATE TABLE book_reviews_cache (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        rating REAL,
        review_count INTEGER DEFAULT 0,
        data JSONB DEFAULT '{}',
        fetched_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (book_id, source)
    );

    -- ============================================================
    -- INCOMING SCANNER
    -- ============================================================
    CREATE TABLE incoming_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        file_path TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_size BIGINT DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'rejected', 'duplicate', 'processing')),
        parsed_title TEXT,
        parsed_author TEXT,
        proposed_metadata JSONB DEFAULT '{}',
        matched_book_id UUID REFERENCES books(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    -- ============================================================
    -- JOBS (async background tasks)
    -- ============================================================
    CREATE TABLE jobs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        job_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'complete', 'failed')),
        progress REAL DEFAULT 0,
        book_id UUID REFERENCES books(id) ON DELETE SET NULL,
        user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        params JSONB DEFAULT '{}',
        result JSONB DEFAULT '{}',
        error TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX jobs_status_idx ON jobs(status);

    CREATE TABLE job_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        message TEXT NOT NULL,
        level TEXT DEFAULT 'info',
        created_at TIMESTAMPTZ DEFAULT now()
    );

    -- ============================================================
    -- TASTE PROFILES (recommendations)
    -- ============================================================
    CREATE TABLE taste_profiles (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
        genre_weights JSONB DEFAULT '{}',
        author_weights JSONB DEFAULT '{}',
        theme_weights JSONB DEFAULT '{}',
        rebuilt_at TIMESTAMPTZ DEFAULT now()
    );

    DO $$ BEGIN
        ALTER TABLE taste_profiles ADD COLUMN taste_embedding vector(384);
    EXCEPTION WHEN undefined_object THEN NULL; END $$;

    -- ============================================================
    -- AUDIO DIAGNOSTICS
    -- ============================================================
    CREATE TABLE audio_diagnostics (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        file_id UUID NOT NULL REFERENCES book_files(id) ON DELETE CASCADE,
        noise_floor_db REAL,
        hiss_score INTEGER DEFAULT 0,
        crackle_score INTEGER DEFAULT 0,
        hum_score INTEGER DEFAULT 0,
        clipping_pct REAL DEFAULT 0,
        dynamic_range_lufs REAL,
        overall_score INTEGER DEFAULT 0,
        recommended_profile TEXT,
        details JSONB DEFAULT '{}',
        diagnosed_at TIMESTAMPTZ DEFAULT now()
    );

    -- ============================================================
    -- SYNC MAPS (text↔audio position mapping)
    -- ============================================================
    CREATE TABLE sync_maps (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        text_file_id UUID NOT NULL REFERENCES book_files(id) ON DELETE CASCADE,
        audio_file_id UUID NOT NULL REFERENCES book_files(id) ON DELETE CASCADE,
        chapter_index INTEGER NOT NULL,
        mappings JSONB NOT NULL DEFAULT '[]',
        created_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (book_id, text_file_id, audio_file_id, chapter_index)
    );

    -- ============================================================
    -- CONTENT CHUNKS (for AI companion semantic search)
    -- ============================================================
    CREATE TABLE content_chunks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        chapter_index INTEGER DEFAULT 0,
        chunk_index INTEGER DEFAULT 0,
        text_content TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX content_chunks_book_idx ON content_chunks(book_id, chapter_index, chunk_index);

    DO $$ BEGIN
        ALTER TABLE content_chunks ADD COLUMN embedding vector(384);
        CREATE INDEX content_chunks_embedding_idx ON content_chunks USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100);
    EXCEPTION WHEN undefined_object THEN NULL; END $$;

    -- ============================================================
    -- PODCAST FEEDS
    -- ============================================================
    CREATE TABLE podcast_feeds (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        schedule TEXT NOT NULL DEFAULT 'daily' CHECK (schedule IN ('daily', 'weekdays', 'weekly', 'twice_weekly')),
        release_time TEXT DEFAULT '08:00',
        start_date DATE DEFAULT CURRENT_DATE,
        created_at TIMESTAMPTZ DEFAULT now()
    );

    -- ============================================================
    -- SEARCH VECTOR TRIGGER
    -- ============================================================
    CREATE OR REPLACE FUNCTION books_search_vector_update() RETURNS trigger AS $$
    BEGIN
        NEW.search_vector :=
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.title, ''))), 'A') ||
            setweight(to_tsvector('simple', unaccent(coalesce(NEW.description, ''))), 'C');
        NEW.updated_at := now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER books_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, description ON books
        FOR EACH ROW EXECUTE FUNCTION books_search_vector_update();

    -- Sort title auto-generation
    CREATE OR REPLACE FUNCTION books_sort_title_update() RETURNS trigger AS $$
    BEGIN
        IF NEW.sort_title IS NULL THEN
            NEW.sort_title := regexp_replace(lower(NEW.title), '^(the|a|an|le|la|les|un|une|der|die|das|el|los|las)\\s+', '', 'i');
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER books_sort_title_trigger
        BEFORE INSERT OR UPDATE OF title ON books
        FOR EACH ROW EXECUTE FUNCTION books_sort_title_update();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS podcast_feeds CASCADE;
    DROP TABLE IF EXISTS content_chunks CASCADE;
    DROP TABLE IF EXISTS sync_maps CASCADE;
    DROP TABLE IF EXISTS audio_diagnostics CASCADE;
    DROP TABLE IF EXISTS taste_profiles CASCADE;
    DROP TABLE IF EXISTS job_logs CASCADE;
    DROP TABLE IF EXISTS jobs CASCADE;
    DROP TABLE IF EXISTS incoming_items CASCADE;
    DROP TABLE IF EXISTS book_reviews_cache CASCADE;
    DROP TABLE IF EXISTS book_translations CASCADE;
    DROP TABLE IF EXISTS book_links CASCADE;
    DROP TABLE IF EXISTS collection_books CASCADE;
    DROP TABLE IF EXISTS collections CASCADE;
    DROP TABLE IF EXISTS book_notes CASCADE;
    DROP TABLE IF EXISTS annotations CASCADE;
    DROP TABLE IF EXISTS bookmarks CASCADE;
    DROP TABLE IF EXISTS reading_progress CASCADE;
    DROP TABLE IF EXISTS audio_chapters CASCADE;
    DROP TABLE IF EXISTS book_files CASCADE;
    DROP TABLE IF EXISTS books_languages CASCADE;
    DROP TABLE IF EXISTS books_publishers CASCADE;
    DROP TABLE IF EXISTS books_series CASCADE;
    DROP TABLE IF EXISTS books_tags CASCADE;
    DROP TABLE IF EXISTS books_authors CASCADE;
    DROP TABLE IF EXISTS languages CASCADE;
    DROP TABLE IF EXISTS publishers CASCADE;
    DROP TABLE IF EXISTS series CASCADE;
    DROP TABLE IF EXISTS tags CASCADE;
    DROP TABLE IF EXISTS authors CASCADE;
    DROP TABLE IF EXISTS books CASCADE;
    DROP TABLE IF EXISTS user_preferences CASCADE;
    DROP TABLE IF EXISTS users CASCADE;
    DROP FUNCTION IF EXISTS books_search_vector_update CASCADE;
    DROP FUNCTION IF EXISTS books_sort_title_update CASCADE;
    """)
