"""Shared producer/consumer contract for Job Browser embeddings."""

EMBEDDING_DIMENSIONS = 384
EMBEDDING_DOCUMENT_CONTRACT = "job-description-v1"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

RANKED_RESULT_LIMIT = 1000
HYBRID_CANDIDATE_LIMIT = 2000
