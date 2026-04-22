"""Tests for embeddings."""
from brainycat.embeddings import _text_to_vector
import math

def test_vector_dimension() -> None:
    vec = _text_to_vector("hello world")
    assert len(vec) == 384

def test_vector_normalized() -> None:
    vec = _text_to_vector("hello world this is a test")
    magnitude = math.sqrt(sum(x*x for x in vec))
    assert abs(magnitude - 1.0) < 0.01

def test_similar_texts_closer() -> None:
    v1 = _text_to_vector("romance love passion heart")
    v2 = _text_to_vector("romance love desire heart")
    v3 = _text_to_vector("quantum physics mathematics")
    # Cosine similarity
    sim12 = sum(a*b for a,b in zip(v1,v2))
    sim13 = sum(a*b for a,b in zip(v1,v3))
    assert sim12 > sim13  # romance texts more similar than romance vs physics

def test_deterministic() -> None:
    v1 = _text_to_vector("test input")
    v2 = _text_to_vector("test input")
    assert v1 == v2
