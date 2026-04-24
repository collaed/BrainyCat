"""Shared Pydantic models for API routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AuthorUpdate(BaseModel):
    author: str


class CreateSeriesBody(BaseModel):
    series_name: str
    book_ids: list[str]


class MergeAuthorsBody(BaseModel):
    keep_id: str
    merge_id: str


class LinkDuplicateBody(BaseModel):
    book_a_id: str
    book_b_id: str
    link_type: str = "edition"


class BatchActionsBody(BaseModel):
    actions: list[dict[str, Any]]


class ProgressUpdate(BaseModel):
    position: str | None = None
    position_timestamp: float | None = None
    percentage: float = 0
    is_finished: bool = False


class BookmarkCreate(BaseModel):
    position: str
    title: str | None = None


class AnnotationCreate(BaseModel):
    cfi_range: str
    text_content: str | None = None
    note: str | None = None
    color: str = "#ffeb3b"


class NoteBody(BaseModel):
    content: str


class BulkTagBody(BaseModel):
    book_ids: list[str]
    tag: str
    action: str = "add"  # add or remove


class BulkEnrichBody(BaseModel):
    book_ids: list[str]


class BatchTagBody(BaseModel):
    book_ids: list[str]
    tags: list[str]


class BatchEnrichBody(BaseModel):
    book_ids: list[str]


class BatchDeleteBody(BaseModel):
    book_ids: list[str]


class MergeBody(BaseModel):
    book_ids: list[str]
    title: str
    author: str = ""
