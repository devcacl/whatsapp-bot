import json
import time
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from app.config import settings


def connect(register_types: bool = True):
    conn = psycopg.connect(settings.database_url, connect_timeout=5)
    if register_types:
        register_vector(conn)
    return conn


def init_db():
    last_error = None
    for _ in range(30):
        try:
            with connect(register_types=False) as conn:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                register_vector(conn)
                conn.execute(f"""CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id text PRIMARY KEY, source_file text NOT NULL, section text NOT NULL,
                    content text NOT NULL, embedding vector({settings.cohere_embed_dim}) NOT NULL,
                    active boolean NOT NULL DEFAULT true, ingested_at timestamptz NOT NULL DEFAULT now())""")
                conn.execute("""CREATE TABLE IF NOT EXISTS inbound_queue (
                    id bigserial PRIMARY KEY, message_id text UNIQUE NOT NULL, sender text NOT NULL,
                    payload jsonb NOT NULL, status text NOT NULL DEFAULT 'pending',
                    attempts int NOT NULL DEFAULT 0, error text, created_at timestamptz NOT NULL DEFAULT now(),
                    claimed_at timestamptz, processed_at timestamptz)""")
                conn.execute("ALTER TABLE inbound_queue ADD COLUMN IF NOT EXISTS claimed_at timestamptz")
                conn.execute("UPDATE inbound_queue SET status='pending',claimed_at=NULL WHERE status='processing' AND claimed_at < now() - interval '2 minutes'")
                conn.execute("""CREATE TABLE IF NOT EXISTS conversation_events (
                    id bigserial PRIMARY KEY, sender_hash text NOT NULL, category text NOT NULL,
                    outcome text NOT NULL, source_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now())""")
                conn.execute("CREATE INDEX IF NOT EXISTS knowledge_embedding_idx ON knowledge_chunks USING hnsw (embedding vector_cosine_ops) WHERE active")
                conn.commit()
                return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"No fue posible inicializar PostgreSQL: {last_error}")


def enqueue(message_id: str, sender: str, payload: dict) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO inbound_queue(message_id,sender,payload) VALUES (%s,%s,%s) ON CONFLICT(message_id) DO NOTHING RETURNING id",
            (message_id, sender, json.dumps(payload)),
        )
        return cur.fetchone() is not None


@contextmanager
def claim_one():
    conn = connect()
    try:
        row = conn.execute("""WITH candidate AS (
            SELECT id FROM inbound_queue WHERE status='pending' ORDER BY id
            FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE inbound_queue q SET status='processing', attempts=attempts+1, claimed_at=now()
          FROM candidate WHERE q.id=candidate.id
          RETURNING q.id,q.message_id,q.sender,q.payload,q.attempts""").fetchone()
        conn.commit()
        yield conn, row
    finally:
        conn.close()


def finish_job(job_id: int, status: str, error: str | None = None):
    with connect() as conn:
        conn.execute("UPDATE inbound_queue SET status=%s,error=%s,payload='{}'::jsonb,processed_at=now() WHERE id=%s", (status, error, job_id))


def save_event(sender_hash: str, category: str, outcome: str, source_ids: list[str]):
    with connect() as conn:
        conn.execute("INSERT INTO conversation_events(sender_hash,category,outcome,source_ids) VALUES (%s,%s,%s,%s)",
                     (sender_hash, category, outcome, json.dumps(source_ids)))


