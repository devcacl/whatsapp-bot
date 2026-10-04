import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.assistant import answer
from app.config import settings
from app.db import claim_one, enqueue, finish_job, init_db, save_event
from app.rag import ingest_directory
from app.whatsapp import extract_messages, send_text, verify_signature

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("admissions-bot")


async def worker():
    while True:
        try:
            with claim_one() as (conn, row):
                if row:
                    job_id, message_id, sender, payload, attempts = row
                    question = payload.get("text", "")
                    try:
                        result = await asyncio.to_thread(answer, question)
                        await send_text(sender, result["text"])
                        sender_hash = hashlib.sha256(sender.encode()).hexdigest()
                        await asyncio.to_thread(save_event, sender_hash, result["category"], result["outcome"], result["sources"])
                        finish_job(job_id, "done")
                    except Exception as exc:
                        log.exception("Fallo al procesar mensaje %s", message_id)
                        if attempts < 3:
                            with conn:
                                conn.execute("UPDATE inbound_queue SET status='pending',error=%s WHERE id=%s", (type(exc).__name__, job_id))
                        else:
                            try:
                                await send_text(sender, "En este momento no puedo completar la consulta. Por favor, intenta más tarde o comunícate con Admisiones.")
                            except Exception:
                                log.exception("No se pudo enviar mensaje de contingencia")
                            finish_job(job_id, "failed", type(exc).__name__)
        except Exception:
            log.exception("Error en worker de WhatsApp")
        await asyncio.sleep(settings.worker_poll_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(init_db)
    task = asyncio.create_task(worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Asistente de Admisiones USTA Tunja", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/ingest")
async def ingest(x_admin_token: str | None = Header(default=None)):
    if not settings.admin_api_token or x_admin_token != settings.admin_api_token:
        raise HTTPException(401, "No autorizado")
    try:
        count = await asyncio.to_thread(ingest_directory)
        return {"status": "indexed", "chunks": count}
    except Exception as exc:
        log.exception("Falló la ingesta")
        raise HTTPException(500, detail=type(exc).__name__) from exc


@app.post("/chat")
async def chat(request: Request, x_admin_token: str | None = Header(default=None)):
    if not settings.admin_api_token or x_admin_token != settings.admin_api_token:
        raise HTTPException(401, "No autorizado")
    body = await request.json()
    question = str(body.get("question", "")).strip()
    if not question or len(question) > 4000:
        raise HTTPException(400, "La pregunta es obligatoria y debe tener máximo 4000 caracteres")
    try:
        result = await asyncio.to_thread(answer, question)
        return {"answer": result["text"], "sources": result["sources"], "outcome": result["outcome"]}
    except Exception as exc:
        log.exception("Fallo en chat de evaluación")
        raise HTTPException(503, "Servicio temporalmente no disponible") from exc


@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    if settings.whatsapp_verify_token and params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == settings.whatsapp_verify_token:
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(403, "Verificación rechazada")


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Firma no válida")
    try:
        payload = await request.json()
        messages = extract_messages(payload)
        for message_id, sender, text in messages:
            await asyncio.to_thread(enqueue, message_id, sender, {"text": text})
        return {"received": True, "queued": len(messages)}
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Webhook inválido")
        raise HTTPException(400, "Evento no válido") from exc


