# claude-instagram-mcp

Local MCP server for Instagram DMs with a SQLite message cache, built for Claude Desktop.

A repo-based fork of [`instagram-dm-mcp`](https://www.npmjs.com/package/instagram-dm-mcp) extended with a local SQLite layer so fetched messages are persisted and searchable without hitting the Instagram API again.

---

## Prerequisites

- Python 3.10+
- Node.js 14+
- pip

---

## Setup

```bash
# 1. Install Node dependencies
npm install

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set credentials
cp .env.example .env
# Edit .env and fill in your Instagram session values
```

### Getting your Instagram credentials

Log into Instagram in a browser, open DevTools → Application → Cookies → `https://www.instagram.com`, and copy:

| Cookie name | `.env` variable |
|---|---|
| `sessionid` | `INSTAGRAM_SESSION_ID` |
| `csrftoken` | `INSTAGRAM_CSRF_TOKEN` |
| `ds_user_id` | `INSTAGRAM_DS_USER_ID` |

Credentials can also be passed as CLI flags (`--session-id`, `--csrf-token`, `--ds-user-id`) or via a `instagram_cookies.json` file in the project root.

---

## Global install

Run once from the project root to make `ig-dm-mcp` available in any terminal:

```bash
npm link
```

To unlink: `npm unlink -g claude-instagram-mcp`

---

## Running

```bash
# Via npm script (.env is loaded automatically — recommended)
npm start

# Or directly (all flags must be on a single line)
node launcher/cli.js start -s <session-id> -c <csrf-token> -d <ds-user-id>

# Load credentials from a JSON file
node launcher/cli.js start --from-file ./instagram_cookies.json
```

**Credential priority** (first match wins):
1. `.env` file in the project root — auto-loaded, no flags needed
2. `INSTAGRAM_SESSION_ID` / `INSTAGRAM_CSRF_TOKEN` / `INSTAGRAM_DS_USER_ID` environment variables
3. CLI flags: `-s <id> -c <token> -d <user-id>`
4. `--from-file <path>` pointing to a JSON credentials file
5. Interactive prompt — if nothing else is found

> **Note:** All flags must be on a **single line**. A line break between `-s` and its value causes a "argument missing" error.

---

## Expected startup output

A successful run looks like this:

```
Using credentials from CLI flags
Starting Instagram DM MCP Server...
[INFO] Credentials loaded from environment variables
[INFO] Instagram client initialised via session ID
[INFO] SQLite DB ready at .../data/instagram.db
[INFO] Starting Instagram DM MCP Server v1.4.0...

╭──────────────────────────────────────────────────────────────────╮
│                                                                  │
│                   ▄▀▀ ▄▀█ █▀▀ ▀█▀ █▀▄▀█ █▀▀ █▀█                  │
│                   █▀  █▀█ ▄▄█  █  █ ▀ █ █▄▄ █▀▀                  │
│                                                                  │
│                         FastMCP 3.4.0                            │
│                     https://gofastmcp.com                        │
│                                                                  │
│           🖥  Server:      InstagramDM, 1.4.0                     │
│                                                                  │
╰──────────────────────────────────────────────────────────────────╯

[INFO] Starting MCP server 'InstagramDM' with transport 'stdio'
```

Key lines to check:
- `Instagram client initialised via session ID` — credentials accepted, login succeeded
- `SQLite DB ready at .../data/instagram.db` — local cache initialised
- `Starting MCP server 'InstagramDM' with transport 'stdio'` — server is ready for connections

---

## LLM integration

Register the server with your LLM tool using the `<llm> install` subcommand. Credentials are read from `.env` automatically, or pass them with flags.

```bash
# Claude Desktop
node launcher/cli.js claude install

# Cursor
node launcher/cli.js cursor install

# Windsurf
node launcher/cli.js windsurf install

# Zed
node launcher/cli.js zed install

# Override credentials at install time
node launcher/cli.js claude install -s <id> -c <token> -d <user-id>
```

Each command writes `node .../launcher/cli.js start` into the target tool's MCP config file. Changes to this repo are picked up immediately after restarting the LLM tool — no re-install needed.

---

## MCP tools

### Live API tools
These call Instagram on every invocation.

| Tool | Args | Description |
|---|---|---|
| `read_dms` | `limit=10` | Read recent inbox threads |
| `send_dm` | `username`, `message` | Send a DM |
| `read_chat` | `thread_id` or `username`, `limit=50` | Full thread message history |
| `health_check` | — | Server status and login state |

### SQLite cache tools
These read from or write to the local `data/instagram.db` file.

| Tool | Args | Description |
|---|---|---|
| `sync_thread` | `thread_id` or `username`, `limit=100` | Fetch from Instagram and persist to local DB |
| `get_cached_threads` | — | List all cached threads (no API call) |
| `search_messages` | `query`, `thread_id?`, `limit=20` | FTS5 full-text search across cached messages |

`search_messages` supports SQLite FTS5 query syntax, e.g. `"hello AND world"`, `"coffee OR tea"`.

---

## Project structure

```
src/
  server.py       FastMCP server — all MCP tools defined here
  instagram.py    instagrapi client wrapper
  db.py           SQLite persistence layer (FTS5 full-text search)
  models.py       Shared TypedDict definitions
launcher/
  index.js        Node.js → Python spawner
  cli.js          CLI: start, <llm> install (claude/cursor/windsurf/zed)
data/             SQLite DB lives here (gitignored)
.env.example      Credential variable template
requirements.txt  Python dependencies
package.json      Node dependencies and npm scripts
```

---

## Database

The SQLite database is created automatically at `data/instagram.db` on first run.

| Table | Purpose |
|---|---|
| `threads` | One row per DM thread, with participants and last sync time |
| `messages` | One row per message, with sender, text, and timestamp |
| `messages_fts` | FTS5 virtual table — triggers keep it in sync with `messages` |

`sync_thread` is the only write path. `get_cached_threads` and `search_messages` are read-only and never touch the Instagram API.

---

## Technical details

| | |
|---|---|
| MCP framework | [FastMCP](https://gofastmcp.com) 3.4.0 |
| Transport | `stdio` — LLM tools communicate over stdin/stdout |
| Instagram library | [instagrapi](https://github.com/subzeroid/instagrapi) |
| DB file | `data/instagram.db` (relative to project root, auto-created) |
| Python required | 3.10+ |
| Node.js required | 14+ |
