#!/usr/bin/env python3
"""
SMS MCP Server - Send and receive SMS via phone gateway + LifeDB.
Works from any machine on Tailscale (desktop, laptop, server).
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

import asyncpg
import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent

# Database connection via Tailscale
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:StrongPassword123@100.127.104.75:5432/lifedb"
)

# SMS Gateway on phone via Tailscale
SMS_GATEWAY_URL = "http://100.83.238.68:8080"
SMS_GATEWAY_AUTH = ("sms", "Lt9VJGAk")

mcp_server = Server("sms")


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=3,
            command_timeout=60,
        )

    async def execute(self, sql: str, *args) -> str:
        if not self.pool:
            await self.connect()
        async with self.pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def fetch(self, sql: str, *args) -> List[Dict[str, Any]]:
        if not self.pool:
            await self.connect()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(row) for row in rows]

    async def fetchrow(self, sql: str, *args) -> Optional[Dict[str, Any]]:
        if not self.pool:
            await self.connect()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else None

    async def close(self):
        if self.pool:
            await self.pool.close()


db = Database()


async def send_via_gateway(phone: str, message: str) -> Dict[str, Any]:
    """Send SMS via phone gateway API."""
    async with httpx.AsyncClient(auth=SMS_GATEWAY_AUTH, timeout=30.0) as client:
        response = await client.post(
            f"{SMS_GATEWAY_URL}/message",
            json={"message": message, "phoneNumbers": [phone]}
        )
        response.raise_for_status()
        return response.json()


@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="send_sms",
            description="""Send an SMS message. Sends via phone gateway AND records in database.

IMPORTANT: Requires user_approved=true. You MUST show the user the exact
message text and recipient, and get explicit approval ("send it", "yes",
"approved") BEFORE calling this tool. Feedback on a draft is NOT approval.

Args:
  phone: Phone number in E.164 format (+1XXXXXXXXXX)
  message: Text message to send
  user_approved: Must be true. Confirms user saw and approved the final message.

Returns confirmation with message ID.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Phone number (+1XXXXXXXXXX format)"
                    },
                    "message": {
                        "type": "string",
                        "description": "Message text to send"
                    },
                    "user_approved": {
                        "type": "boolean",
                        "description": "User has seen and explicitly approved this exact message. Required."
                    }
                },
                "required": ["phone", "message", "user_approved"]
            }
        ),
        Tool(
            name="get_conversations",
            description="""List active SMS conversations with unread counts.

Shows conversations that have unprocessed messages (either unread incoming
or unsent outgoing that haven't been reviewed).

Returns list of contacts with:
- Contact name (or phone if unknown)
- Last message timestamp
- Count of unread incoming messages
- Count of messages after last outgoing (truly new)""",
            inputSchema={
                "type": "object",
                "properties": {},
            }
        ),
        Tool(
            name="get_thread",
            description="""Get full conversation thread with a contact.

Args:
  phone: Phone number to get thread for
  limit: Max messages to return (default 50)

Returns messages in chronological order with direction, content, timestamp.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Phone number (+1XXXXXXXXXX format)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max messages to return (default 50)"
                    }
                },
                "required": ["phone"]
            }
        ),
        Tool(
            name="mark_read",
            description="""Mark all messages in a conversation as read.

Args:
  phone: Phone number of conversation to mark read

Marks both incoming and outgoing messages as processed.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Phone number (+1XXXXXXXXXX format)"
                    }
                },
                "required": ["phone"]
            }
        ),
        Tool(
            name="get_unread",
            description="""Get unread incoming messages across all conversations.

Returns messages that:
1. Are incoming (direction = 'incoming')
2. Have read_at IS NULL
3. Were received AFTER the last outgoing message to that number

This is the "read horizon" model - replying marks prior messages as seen.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max messages to return (default 30)"
                    }
                }
            }
        )
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:

    if name == "send_sms":
        phone = arguments["phone"]
        message = arguments["message"]
        user_approved = arguments.get("user_approved", False)

        if not user_approved:
            return [TextContent(
                type="text",
                text="BLOCKED: user_approved must be true. Show the user the exact message and recipient, get explicit approval ('send it', 'yes', 'approved'), then call again with user_approved=true."
            )]

        try:
            # Send via gateway
            result = await send_via_gateway(phone, message)
            message_id = result.get("id", "unknown")

            # Insert into database with message content
            await db.execute("""
                INSERT INTO sms_messages
                (message_id, direction, phone_number, message, received_at, source)
                VALUES ($1, 'outgoing', $2, $3, NOW(), 'phone')
            """, message_id, phone, message)

            # Get contact name if available
            contact = await db.fetchrow(
                "SELECT name FROM contacts WHERE phone_number = $1", phone
            )
            contact_name = contact["name"] if contact else phone

            return [TextContent(
                type="text",
                text=f"Sent to {contact_name}: \"{message[:50]}{'...' if len(message) > 50 else ''}\"\nMessage ID: {message_id}"
            )]

        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Gateway error: {str(e)}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    elif name == "get_conversations":
        try:
            rows = await db.fetch("""
                WITH last_outgoing AS (
                    SELECT phone_number, MAX(received_at) as last_sent_at
                    FROM sms_messages
                    WHERE direction = 'outgoing'
                    GROUP BY phone_number
                ),
                conversation_stats AS (
                    SELECT
                        s.phone_number,
                        MAX(s.received_at) as last_activity,
                        COUNT(*) FILTER (
                            WHERE s.direction = 'incoming'
                            AND s.read_at IS NULL
                        ) as unread_count,
                        COUNT(*) FILTER (
                            WHERE s.direction = 'incoming'
                            AND s.read_at IS NULL
                            AND (lo.last_sent_at IS NULL OR s.received_at > lo.last_sent_at)
                        ) as truly_new_count
                    FROM sms_messages s
                    LEFT JOIN last_outgoing lo ON s.phone_number = lo.phone_number
                    WHERE s.read_at IS NULL
                    GROUP BY s.phone_number
                )
                SELECT
                    cs.phone_number,
                    COALESCE(c.name, cs.phone_number) as contact_name,
                    cs.last_activity,
                    cs.unread_count,
                    cs.truly_new_count
                FROM conversation_stats cs
                LEFT JOIN contacts c ON cs.phone_number = c.phone_number
                WHERE cs.unread_count > 0 OR cs.truly_new_count > 0
                ORDER BY cs.last_activity DESC
            """)

            if not rows:
                return [TextContent(type="text", text="No unread conversations.")]

            lines = ["# Active Conversations\n"]
            for row in rows:
                name = row["contact_name"]
                new_count = row["truly_new_count"]
                last = row["last_activity"].strftime("%Y-%m-%d %H:%M") if row["last_activity"] else "?"
                lines.append(f"- **{name}**: {new_count} new | last: {last}")

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    elif name == "get_thread":
        phone = arguments["phone"]
        limit = arguments.get("limit", 50)

        try:
            # Get contact name
            contact = await db.fetchrow(
                "SELECT name FROM contacts WHERE phone_number = $1", phone
            )
            contact_name = contact["name"] if contact else phone

            rows = await db.fetch("""
                SELECT direction, message, received_at, read_at
                FROM sms_messages
                WHERE phone_number = $1
                ORDER BY received_at DESC
                LIMIT $2
            """, phone, limit)

            if not rows:
                return [TextContent(type="text", text=f"No messages with {contact_name}")]

            # Reverse to show chronological order
            rows = list(reversed(rows))

            lines = [f"# Thread with {contact_name}\n"]
            for row in rows:
                direction = "→" if row["direction"] == "outgoing" else "←"
                time = row["received_at"].strftime("%m/%d %H:%M") if row["received_at"] else "?"
                msg = row["message"] or "(no content)"
                read = "" if row["read_at"] else " *"
                lines.append(f"{direction} [{time}]{read} {msg}")

            lines.append(f"\n* = unread")
            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    elif name == "mark_read":
        phone = arguments["phone"]

        try:
            result = await db.execute("""
                UPDATE sms_messages
                SET read_at = NOW(), status = 'read'
                WHERE phone_number = $1 AND read_at IS NULL
            """, phone)

            # Get contact name
            contact = await db.fetchrow(
                "SELECT name FROM contacts WHERE phone_number = $1", phone
            )
            contact_name = contact["name"] if contact else phone

            return [TextContent(
                type="text",
                text=f"Marked conversation with {contact_name} as read."
            )]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    elif name == "get_unread":
        limit = arguments.get("limit", 30)

        try:
            rows = await db.fetch("""
                WITH last_outgoing AS (
                    SELECT phone_number, MAX(received_at) as last_sent_at
                    FROM sms_messages
                    WHERE direction = 'outgoing'
                    GROUP BY phone_number
                )
                SELECT
                    COALESCE(c.name, s.phone_number) as sender,
                    s.phone_number,
                    s.message,
                    s.received_at
                FROM sms_messages s
                LEFT JOIN contacts c ON s.phone_number = c.phone_number
                LEFT JOIN last_outgoing lo ON s.phone_number = lo.phone_number
                WHERE s.direction = 'incoming'
                  AND s.read_at IS NULL
                  AND (lo.last_sent_at IS NULL OR s.received_at > lo.last_sent_at)
                ORDER BY s.received_at DESC
                LIMIT $1
            """, limit)

            if not rows:
                return [TextContent(type="text", text="No unread messages.")]

            lines = ["# Unread Messages\n"]
            current_sender = None
            for row in rows:
                sender = row["sender"]
                if sender != current_sender:
                    if current_sender:
                        lines.append("")
                    lines.append(f"**{sender}**")
                    current_sender = sender

                time = row["received_at"].strftime("%m/%d %H:%M") if row["received_at"] else "?"
                msg = row["message"] or "(no content)"
                lines.append(f"  [{time}] {msg}")

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


def main():
    from mcp.server.stdio import stdio_server
    import sys

    async def run():
        try:
            async with stdio_server() as (read_stream, write_stream):
                await mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options()
                )
        except Exception as e:
            print(f"MCP server error: {e}", file=sys.stderr)
        finally:
            await db.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
