"""Idempotently add explicit embedding-document provenance to an existing DB."""

from sqlalchemy import text

from app.database import engine


def upgrade_job_embedding_contract() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE job_embeddings "
                "ADD COLUMN IF NOT EXISTS document_contract VARCHAR(64)"
            )
        )
        connection.execute(
            text(
                "UPDATE job_embeddings SET document_contract = 'legacy' "
                "WHERE document_contract IS NULL"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE job_embeddings ALTER COLUMN document_contract "
                "SET DEFAULT 'legacy'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE job_embeddings ALTER COLUMN document_contract SET NOT NULL"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_job_embeddings_document_contract "
                "ON job_embeddings (document_contract)"
            )
        )


if __name__ == "__main__":
    upgrade_job_embedding_contract()
    print("Job embedding document-contract schema is current.")
