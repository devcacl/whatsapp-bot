import hashlib
import hmac

import httpx

from app.config import settings


def verify_signature(raw: bytes, signature: str | None) -> bool:
    if not settings.whatsapp_app_secret:
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(settings.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def send_text(to: str, text: str):
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id or not settings.whatsapp_api_version:
        raise RuntimeError("WhatsApp Cloud API no está configurado")
    url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/messages"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            json={"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                  "type": "text", "text": {"preview_url": False, "body": text}})
        response.raise_for_status()


def extract_messages(payload: dict):
    found = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") == "text" and message.get("text", {}).get("body"):
                    found.append((message.get("id"), message.get("from"), message["text"]["body"]))
    return [(i, s, t) for i, s, t in found if i and s]


