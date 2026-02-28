# SMS MCP Server

MCP server for sending/receiving SMS via phone gateway + LifeDB.

## Contents

| File | Purpose |
|------|---------|
| `server.py` | MCP server implementation with all SMS tools |
| `requirements.txt` | Python dependencies (asyncpg, httpx, mcp) |
| `venv/` | Python virtual environment |

## Tools

| Tool | Description |
|------|-------------|
| `send_sms` | Send SMS + record in DB (captures message content) |
| `get_conversations` | List active conversations with unread counts |
| `get_thread` | Get full message thread with a contact |
| `mark_read` | Mark conversation as read |
| `get_unread` | Get unread incoming messages (read horizon model) |

## Architecture

```
Claude → MCP Server → SMS Gateway (phone:8080) → Carrier SMS
                   ↓
                LifeDB (records message with content)
```

The phone's SMS Gateway webhook (`sms:sent`) doesn't include message content.
This MCP server captures content at send time by inserting directly to DB.

## Setup

```bash
# Create venv (no symlinks for Obsidian compatibility)
cd /mnt/d/obs/life-code/sms-mcp
python3 -m venv --copies venv
rm -rf venv/lib64 && cp -r venv/lib venv/lib64
./venv/bin/pip install -r requirements.txt
```

## MCP Config

Add to `.mcp.json`:

```json
{
  "sms": {
    "command": "/path/to/sms-mcp/venv/bin/python",
    "args": ["/path/to/sms-mcp/server.py"]
  }
}
```

## Server Setup (red)

The server needs its own venv since paths differ:

```bash
ssh red
cd /srv/obs/life-code/sms-mcp  # or wherever obs is mounted
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Then add to server's Claude Code config with server-appropriate paths.

## Dependencies

- `asyncpg` - PostgreSQL async driver
- `httpx` - Async HTTP client for SMS Gateway
- `mcp` - MCP server framework

## Related

- `/life/infra/sms-infrastructure.md` - Full SMS architecture
- `/life-code/lifedb/` - LifeDB MCP server
- SMS Gateway app on phone (port 8080)
