from __future__ import annotations

# This migration is intentionally a no-op.
#
# Migration 0001_initial already creates the `memory_chunks.embedding` column as
# Vector(256) and builds the HNSW cosine index `ix_memory_chunks_embedding_hnsw`.
#
# A previous version of this file used op.get_bind() (synchronous) which raises
# MissingGreenlet under the project's async Alembic env.py. That approach has
# been removed. If you are upgrading a database that was created before 0001 used
# Vector, run the SQL below manually once, then apply this migration:
#
#   ALTER TABLE memory_chunks
#     ALTER COLUMN embedding TYPE vector(256) USING embedding::vector(256);
#   CREATE INDEX IF NOT EXISTS ix_memory_chunks_embedding_hnsw
#     ON memory_chunks USING hnsw (embedding vector_cosine_ops);
from alembic import op

revision = "0002_memory_embedding_vector"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure the pgvector extension is present (idempotent).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Nothing to reverse — the column and index belong to 0001.
    pass