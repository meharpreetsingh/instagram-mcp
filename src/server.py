import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any
from urllib.parse import unquote

from fastmcp import FastMCP
from instagrapi.exceptions import (
    LoginRequired,
    ClientLoginRequired,
    ClientUnauthorizedError,
    ClientForbiddenError,
    ReloginAttemptExceeded,
)

sys.path.insert(0, str(Path(__file__).parent))
import instagram as ig
import db as db_mod
from models import Credentials

_SESSION_EXPIRED_EXCEPTIONS = (
    LoginRequired,
    ClientLoginRequired,
    ClientUnauthorizedError,
    ClientForbiddenError,
    ReloginAttemptExceeded,
)

_SESSION_EXPIRED_MSG = (
    "Instagram session has expired. "
    "Update INSTAGRAM_SESSION_ID in .env with a fresh session ID and restart the server."
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%m/%d/%y %H:%M:%S",
    stream=sys.stderr,
)

VERSION = "1.4.0"
startup_time = time.time()
POLL_INTERVAL = int(os.environ.get("INSTAGRAM_POLL_INTERVAL", "300"))  # seconds; 0 = disabled


async def _auto_sync_loop():
    if POLL_INTERVAL <= 0:
        return
    logging.info("Auto-sync started (interval: %ds)", POLL_INTERVAL)
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        if not client or not getattr(client, "user_id", None):
            continue
        try:
            threads = ig.fetch_inbox(client, limit=20)
            total_new = 0
            for t in threads:
                db_mod.upsert_thread(conn, t)
                total_new += db_mod.upsert_messages(conn, t["thread_id"], t["messages"])
            logging.info("Auto-sync: %d threads checked, %d new messages", len(threads), total_new)
        except _SESSION_EXPIRED_EXCEPTIONS:
            logging.warning("Auto-sync: session expired, skipping cycle")
        except Exception as e:
            logging.error("Auto-sync error: %s", e)


@asynccontextmanager
async def _lifespan(server):
    task = asyncio.create_task(_auto_sync_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


mcp = FastMCP("InstagramDM", version=VERSION, lifespan=_lifespan)

# --- Auth ---
def _decode(creds: Credentials) -> Credentials:
    return {k: unquote(v) if isinstance(v, str) else v for k, v in creds.items()}


def _load_credentials() -> Credentials:
    sessionid = os.environ.get("INSTAGRAM_SESSION_ID")
    csrftoken = os.environ.get("INSTAGRAM_CSRF_TOKEN")
    ds_user_id = os.environ.get("INSTAGRAM_DS_USER_ID")

    if sessionid and csrftoken and ds_user_id:
        logging.info("Credentials loaded from environment variables")
        return _decode({"sessionid": sessionid, "csrftoken": csrftoken, "ds_user_id": ds_user_id})

    combined = os.environ.get("INSTAGRAM_COOKIES")
    if combined:
        try:
            data = json.loads(combined)
            logging.info("Credentials loaded from INSTAGRAM_COOKIES env var")
            return _decode(data)
        except json.JSONDecodeError:
            logging.error("INSTAGRAM_COOKIES is not valid JSON")

    cookie_file = Path(__file__).parent.parent / "instagram_cookies.json"
    if cookie_file.exists():
        try:
            data = json.loads(cookie_file.read_text())
            logging.info("Credentials loaded from instagram_cookies.json")
            return _decode(data)
        except json.JSONDecodeError:
            logging.error("instagram_cookies.json is not valid JSON")

    logging.warning("No Instagram credentials found — some tools will fail")
    return {}


credentials = _load_credentials()
client = None
_client_init_error: str | None = None
_client_init_error_detail: str | None = None

if not credentials.get("sessionid"):
    _client_init_error = "no_credentials"
else:
    try:
        client = ig.init_client(credentials)
    except _SESSION_EXPIRED_EXCEPTIONS as e:
        logging.error("Instagram session is expired or invalid: %s", e)
        _client_init_error = "session_expired"
        _client_init_error_detail = str(e)
    except Exception as e:
        logging.error("Failed to initialise Instagram client: %s", e)
        _client_init_error = "init_failed"
        _client_init_error_detail = str(e)

# --- DB ---
_db_path = Path(__file__).parent.parent / "data" / "instagram.db"
conn = db_mod.init_db(_db_path)
logging.info("SQLite DB ready at %s", _db_path)


# ── Existing tools ─────────────────────────────────────────────────────────────

@mcp.tool()
def read_dms(limit: int = 10) -> Dict[str, Any]:
    """Read recent Instagram DMs from the inbox.

    Args:
        limit: Number of threads to fetch (default 10).
    """
    if not client or not getattr(client, "user_id", None):
        return {"status": "error", "message": "Instagram client not initialised — check credentials"}
    try:
        threads = ig.fetch_inbox(client, limit)
        messages = []
        for thread in threads:
            thread_info = {
                "thread_id": thread["thread_id"],
                "thread_title": thread["thread_title"],
                "users": thread["participants"],
            }
            for msg in thread["messages"]:
                messages.append({**msg, "thread": thread_info})
        return {"status": "success", "messages": messages}
    except _SESSION_EXPIRED_EXCEPTIONS as e:
        logging.warning("read_dms: session expired (%s)", e)
        return {"status": "error", "error_code": "session_expired", "message": _SESSION_EXPIRED_MSG}
    except Exception as e:
        logging.error("read_dms error: %s", e)
        return {"status": "error", "message": str(e)}


@mcp.tool()
def send_dm(username: str, message: str) -> Dict[str, Any]:
    """Send a direct message to an Instagram user.

    Args:
        username: Instagram username of the recipient.
        message: Message text to send.
    """
    if not client or not getattr(client, "user_id", None):
        return {"status": "error", "message": "Instagram client not initialised — check credentials"}
    if not username or not message:
        return {"status": "error", "message": "username and message are required"}
    try:
        return ig.send_message(client, username, message)
    except _SESSION_EXPIRED_EXCEPTIONS as e:
        logging.warning("send_dm: session expired (%s)", e)
        return {"status": "error", "error_code": "session_expired", "message": _SESSION_EXPIRED_MSG}
    except Exception as e:
        logging.error("send_dm error: %s", e)
        return {"status": "error", "message": str(e)}


@mcp.tool()
def read_chat(thread_id: str = "", username: str = "", limit: int = 50) -> Dict[str, Any]:
    """Read full message history for a specific DM thread.

    Args:
        thread_id: Thread ID (takes priority over username).
        username: Instagram username for 1-to-1 chats.
        limit: Max messages to retrieve (default 50).
    """
    if not client or not getattr(client, "user_id", None):
        return {"status": "error", "message": "Instagram client not initialised — check credentials"}
    if not thread_id and not username:
        return {"status": "error", "message": "Provide either thread_id or username"}
    try:
        if thread_id:
            thread = ig.fetch_thread(client, thread_id, limit)
        else:
            thread = ig.fetch_thread_by_username(client, username)
        return {
            "status": "success",
            "thread_id": thread["thread_id"],
            "thread_title": thread["thread_title"],
            "is_group": thread["is_group"],
            "participants": thread["participants"],
            "message_count": len(thread["messages"]),
            "messages": thread["messages"],
        }
    except _SESSION_EXPIRED_EXCEPTIONS as e:
        logging.warning("read_chat: session expired (%s)", e)
        return {"status": "error", "error_code": "session_expired", "message": _SESSION_EXPIRED_MSG}
    except Exception as e:
        logging.error("read_chat error: %s", e)
        return {"status": "error", "message": str(e)}


@mcp.tool()
def health_check() -> Dict[str, Any]:
    """Check server health and Instagram login status."""
    is_logged_in = (
        client is not None
        and hasattr(client, "user_id")
        and client.user_id is not None
    )
    result: Dict[str, Any] = {
        "status": "healthy",
        "service": "InstagramDM MCP Server",
        "version": VERSION,
        "logged_in": str(is_logged_in),
        "db_path": str(_db_path),
        "poll_interval_seconds": POLL_INTERVAL,
    }
    if not is_logged_in and _client_init_error:
        result["login_error"] = _client_init_error
        if _client_init_error == "session_expired":
            result["login_hint"] = (
                "Your Instagram session has expired. "
                "Generate a new session ID and update INSTAGRAM_SESSION_ID in .env, then restart."
            )
        elif _client_init_error == "no_credentials":
            result["login_hint"] = (
                "No Instagram credentials found. "
                "Set INSTAGRAM_SESSION_ID in .env and restart."
            )
        else:
            result["login_hint"] = "Instagram client failed to initialise. Check server logs for details."
    return result


# ── New DB-backed tools ─────────────────────────────────────────────────────────

@mcp.tool()
def sync_thread(thread_id: str = "", username: str = "", limit: int = 100) -> Dict[str, Any]:
    """Fetch a thread from Instagram and cache it in the local SQLite database.

    Args:
        thread_id: Thread ID to sync (takes priority over username).
        username: Instagram username for 1-to-1 chats.
        limit: Max messages to fetch and store (default 100).
    """
    if not client or not getattr(client, "user_id", None):
        return {"status": "error", "message": "Instagram client not initialised — check credentials"}
    if not thread_id and not username:
        return {"status": "error", "message": "Provide either thread_id or username"}
    try:
        if thread_id:
            thread = ig.fetch_thread(client, thread_id, limit)
        else:
            thread = ig.fetch_thread_by_username(client, username)

        db_mod.upsert_thread(conn, thread)
        inserted = db_mod.upsert_messages(conn, thread["thread_id"], thread["messages"])

        return {
            "status": "success",
            "thread_id": thread["thread_id"],
            "thread_title": thread["thread_title"],
            "participants": thread["participants"],
            "fetched": len(thread["messages"]),
            "new_messages_stored": inserted,
        }
    except _SESSION_EXPIRED_EXCEPTIONS as e:
        logging.warning("sync_thread: session expired (%s)", e)
        return {"status": "error", "error_code": "session_expired", "message": _SESSION_EXPIRED_MSG}
    except Exception as e:
        logging.error("sync_thread error: %s", e)
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_cached_threads() -> Dict[str, Any]:
    """List all threads stored in the local SQLite cache (no API call)."""
    try:
        threads = db_mod.get_threads(conn)
        return {"status": "success", "count": len(threads), "threads": threads}
    except Exception as e:
        logging.error("get_cached_threads error: %s", e)
        return {"status": "error", "message": str(e)}


@mcp.tool()
def search_messages(query: str, thread_id: str = "", limit: int = 20) -> Dict[str, Any]:
    """Full-text search across all cached messages in the local SQLite database.

    Args:
        query: Search terms (SQLite FTS5 syntax supported, e.g. "hello AND world").
        thread_id: Restrict search to a specific thread (optional).
        limit: Max results to return (default 20).
    """
    if not query:
        return {"status": "error", "message": "query is required"}
    try:
        results = db_mod.search_messages(conn, query, thread_id or None, limit)
        return {"status": "success", "count": len(results), "results": results}
    except Exception as e:
        logging.error("search_messages error: %s", e)
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    logging.info("Starting Instagram DM MCP Server v%s...", VERSION)
    try:
        mcp.run()
    except (KeyboardInterrupt, SystemExit):
        logging.info("Server stopped.")
    except BaseException as exc:
        if isinstance(exc, BaseExceptionGroup):
            oserrs = [e for e in exc.exceptions if isinstance(e, OSError)]
            if len(oserrs) == len(exc.exceptions):
                logging.info("Server stopped.")
                sys.exit(0)
        raise
