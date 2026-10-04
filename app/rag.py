import hashlib
from pathlib import Path

import cohere
from pgvector import Vector

from app.config import settings
from app.db import connect


def _embed_client():
    if not settings.cohere_api_key:
        raise RuntimeError("Falta COHERE_API_KEY")
    return cohere.ClientV2(api_key=settings.cohere_api_key)


def _split_markdown(text: str, max_chars: int = 4500):
    sections, current_title, current = [], "Documento", []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                sections.append((current_title, "\n".join(current).strip()))
            current_title, current = line[3:].strip(), [line]
        else:
            current.append(line)
    if current:
        sections.append((current_title, "\n".join(current).strip()))
    chunks = []
    for title, body in sections:
        if not body:
            continue
        if len(body) <= max_chars:
            chunks.append((title, body))
            continue
        paragraphs, piece = body.split("\n\n"), ""
        for paragraph in paragraphs:
            if len(piece) + len(paragraph) > max_chars and piece:
                chunks.append((title, piece.strip()))
                piece = ""
            piece += paragraph + "\n\n"
        if piece.strip():
            chunks.append((title, piece.strip()))
    return chunks


def ingest_directory(directory: str | None = None):
    root = Path(directory or settings.knowledge_dir)
    files = sorted(root.glob("*.md"))
    if not files:
        raise RuntimeError(f"No se encontraron archivos Markdown en {root}")
    all_chunks = []
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        all_chunks.extend((path.name, title, body) for title, body in _split_markdown(text))
    client = _embed_client()
    texts = [f"Fuente: {source}\nSección: {title}\n{body}" for source, title, body in all_chunks]
    embedded = []
    batch_size = 90
    for start in range(0, len(texts), batch_size):
        result = client.embed(model=settings.cohere_embed_model, input_type="search_document",
                              embedding_types=["float"], texts=texts[start:start + batch_size])
        embedded.extend(result.embeddings.float_)
    if any(len(vector) != settings.cohere_embed_dim for vector in embedded):
        raise RuntimeError("La dimensión devuelta por Cohere no coincide con COHERE_EMBED_DIM")
    with connect() as conn:
        conn.execute("UPDATE knowledge_chunks SET active=false")
        for (source, title, body), vector in zip(all_chunks, embedded):
            key = hashlib.sha256(f"{source}|{title}|{body}".encode()).hexdigest()
            conn.execute("""INSERT INTO knowledge_chunks(id,source_file,section,content,embedding,active)
                VALUES (%s,%s,%s,%s,%s,true) ON CONFLICT(id) DO UPDATE SET
                source_file=excluded.source_file,section=excluded.section,content=excluded.content,
                embedding=excluded.embedding,active=true,ingested_at=now()""", (key, source, title, body, Vector(vector)))
        conn.commit()
    return len(all_chunks)


def retrieve(question: str):
    client = _embed_client()
    result = client.embed(model=settings.cohere_embed_model, input_type="search_query",
                          embedding_types=["float"], texts=[question])
    vector = result.embeddings.float_[0]
    if len(vector) != settings.cohere_embed_dim:
        raise RuntimeError("La dimensión de consulta no coincide con la dimensión indexada")
    with connect() as conn:
        rows = conn.execute("""SELECT id,source_file,section,content,1-(embedding <=> %s) AS score
            FROM knowledge_chunks WHERE active=true ORDER BY embedding <=> %s LIMIT %s""",
            (Vector(vector), Vector(vector), settings.top_k)).fetchall()
    if not rows:
        return []
    reranked = client.rerank(model=settings.cohere_rerank_model, query=question,
                             documents=[r[3] for r in rows], top_n=min(6, len(rows)))
    return [{"id": rows[x.index][0], "source": rows[x.index][1], "section": rows[x.index][2],
             "content": rows[x.index][3], "score": float(rows[x.index][4])}
            for x in reranked.results if float(rows[x.index][4]) >= settings.min_relevance]


