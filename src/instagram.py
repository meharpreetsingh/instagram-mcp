import logging
from typing import Optional
import instagrapi
from models import Credentials, Thread, Message


def init_client(credentials: Credentials) -> instagrapi.Client:
    client = instagrapi.Client()
    sessionid = credentials.get("sessionid")
    if not sessionid:
        raise ValueError("sessionid is required")
    client.login_by_sessionid(sessionid)
    logging.info("Instagram client initialised via session ID")
    return client


def _thread_to_dict(thread) -> Thread:
    participants = [u.username for u in thread.users if hasattr(u, "username")]
    messages: list[Message] = []
    for msg in thread.messages:
        sender = next(
            (u.username for u in thread.users if hasattr(u, "username") and u.pk == msg.user_id),
            str(msg.user_id) if msg.user_id else None,
        )
        messages.append({
            "message_id": str(msg.id),
            "thread_id": str(thread.id),
            "sender": sender,
            "sender_id": str(msg.user_id) if msg.user_id else None,
            "text": msg.text,
            "item_type": str(msg.item_type) if msg.item_type else None,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
        })
    return {
        "thread_id": str(thread.id),
        "thread_title": thread.thread_title,
        "is_group": bool(thread.is_group),
        "participants": participants,
        "messages": messages,
    }


def fetch_inbox(client: instagrapi.Client, limit: int = 10) -> list[Thread]:
    threads = client.direct_threads(amount=limit)
    return [_thread_to_dict(t) for t in threads]


def fetch_thread(client: instagrapi.Client, thread_id: str, limit: int = 50) -> Thread:
    thread = client.direct_thread(thread_id, amount=limit)
    result = _thread_to_dict(thread)
    result["messages"] = list(reversed(result["messages"]))  # oldest first
    return result


def fetch_thread_by_username(client: instagrapi.Client, username: str) -> Thread:
    user_id = client.user_id_from_username(username)
    thread = client.direct_thread_by_participants([user_id])
    result = _thread_to_dict(thread)
    result["messages"] = list(reversed(result["messages"]))
    return result


def send_message(client: instagrapi.Client, username: str, message: str) -> dict:
    recipient_id = client.user_id_from_username(username)
    client.direct_send(message, [recipient_id])
    logging.info("Sent DM to %s", username)
    return {"status": "success", "message": f"Sent DM to {username}"}
