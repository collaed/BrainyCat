"""Tests for TF-IDF embeddings."""

import math

from brainycat.embeddings import _text_to_vector, _tokenize, _term_freq


def test_vector_dimension() -> None:
    vec = _text_to_vector("hello world testing embeddings")
    assert len(vec) == 384


def test_vector_normalized() -> None:
    vec = _text_to_vector("hello world this is a test of embeddings")
    magnitude = math.sqrt(sum(x * x for x in vec))
    assert abs(magnitude - 1.0) < 0.01


def test_similar_texts_closer() -> None:
    v1 = _text_to_vector("romance love passion heart desire")
    v2 = _text_to_vector("romance love desire heart longing")
    v3 = _text_to_vector("quantum physics mathematics topology")
    sim12 = sum(a * b for a, b in zip(v1, v2))
    sim13 = sum(a * b for a, b in zip(v1, v3))
    assert sim12 > sim13


def test_deterministic() -> None:
    v1 = _text_to_vector("test input for embedding")
    v2 = _text_to_vector("test input for embedding")
    assert v1 == v2


def test_tokenize_removes_stopwords() -> None:
    tokens = _tokenize("the quick brown fox and the lazy dog")
    assert "the" not in tokens
    assert "and" not in tokens
    assert "quick" in tokens
    assert "brown" in tokens


def test_tokenize_french_stopwords() -> None:
    tokens = _tokenize("les aventures dans la forêt enchantée")
    assert "les" not in tokens
    assert "dans" not in tokens
    assert "aventures" in tokens


def test_term_freq() -> None:
    tf = _term_freq(["cat", "dog", "cat", "bird"])
    assert tf["cat"] == 0.5
    assert tf["dog"] == 0.25
