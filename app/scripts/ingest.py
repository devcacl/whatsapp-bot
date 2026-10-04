from app.db import init_db
from app.rag import ingest_directory

if __name__ == "__main__":
    init_db()
    print(f"Fragmentos indexados: {ingest_directory()}")


