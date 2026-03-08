import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { shutdown } from '@life/common';
import { sendViaGateway } from './gateway.js';
import {
  getConversations,
  getThread,
  getUnread,
  markRead,
  getContactName,
  insertOutgoingSms,
} from './queries.js';

const server = new McpServer({
  name: 'sms',
  version: '1.0.0',
});

// --- send_sms ---
server.tool(
  'send_sms',
  `Send an SMS message. Sends via phone gateway AND records in database.

IMPORTANT: Requires user_approved=true. You MUST show the user the exact
message text and recipient, and get explicit approval ("send it", "yes",
"approved") BEFORE calling this tool. Feedback on a draft is NOT approval.`,
  {
    phone: z.string().describe('Phone number (+1XXXXXXXXXX format)'),
    message: z.string().describe('Message text to send'),
    user_approved: z
      .boolean()
      .describe('User has seen and explicitly approved this exact message'),
  },
  async ({ phone, message, user_approved }) => {
    if (!user_approved) {
      return {
        content: [
          {
            type: 'text',
            text: "BLOCKED: user_approved must be true. Show the user the exact message and recipient, get explicit approval ('send it', 'yes', 'approved'), then call again with user_approved=true.",
          },
        ],
      };
    }

    try {
      const result = await sendViaGateway(phone, message);
      const messageId = result.id ?? 'unknown';
      await insertOutgoingSms(messageId, phone, message);
      const contactName = await getContactName(phone);
      const preview =
        message.length > 50 ? message.slice(0, 50) + '...' : message;

      return {
        content: [
          {
            type: 'text',
            text: `Sent to ${contactName}: "${preview}"\nMessage ID: ${messageId}`,
          },
        ],
      };
    } catch (err: any) {
      return {
        content: [{ type: 'text', text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  },
);

// --- get_conversations ---
server.tool(
  'get_conversations',
  'List active SMS conversations with unread counts.',
  {},
  async () => {
    try {
      const rows = await getConversations();
      if (rows.length === 0) {
        return {
          content: [{ type: 'text', text: 'No unread conversations.' }],
        };
      }

      const lines = ['# Active Conversations\n'];
      for (const row of rows) {
        const last = row.last_activity
          ? new Date(row.last_activity).toISOString().slice(0, 16).replace('T', ' ')
          : '?';
        lines.push(
          `- **${row.contact_name}**: ${row.truly_new_count} new | last: ${last}`,
        );
      }
      return { content: [{ type: 'text', text: lines.join('\n') }] };
    } catch (err: any) {
      return {
        content: [{ type: 'text', text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  },
);

// --- get_thread ---
server.tool(
  'get_thread',
  'Get full conversation thread with a contact.',
  {
    phone: z.string().describe('Phone number (+1XXXXXXXXXX format)'),
    limit: z
      .number()
      .optional()
      .default(50)
      .describe('Max messages to return'),
  },
  async ({ phone, limit }) => {
    try {
      const contactName = await getContactName(phone);
      const rows = await getThread(phone, limit);

      if (rows.length === 0) {
        return {
          content: [
            { type: 'text', text: `No messages with ${contactName}` },
          ],
        };
      }

      // Reverse to chronological
      rows.reverse();

      const lines = [`# Thread with ${contactName}\n`];
      for (const row of rows) {
        const dir = row.direction === 'outgoing' ? '→' : '←';
        const time = row.received_at
          ? new Date(row.received_at).toISOString().slice(5, 16).replace('T', ' ')
          : '?';
        const msg = row.message || '(no content)';
        const read = row.read_at ? '' : ' *';
        lines.push(`${dir} [${time}]${read} ${msg}`);
      }
      lines.push('\n* = unread');

      return { content: [{ type: 'text', text: lines.join('\n') }] };
    } catch (err: any) {
      return {
        content: [{ type: 'text', text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  },
);

// --- mark_read ---
server.tool(
  'mark_read',
  'Mark all messages in a conversation as read.',
  {
    phone: z.string().describe('Phone number (+1XXXXXXXXXX format)'),
  },
  async ({ phone }) => {
    try {
      await markRead(phone);
      const contactName = await getContactName(phone);
      return {
        content: [
          {
            type: 'text',
            text: `Marked conversation with ${contactName} as read.`,
          },
        ],
      };
    } catch (err: any) {
      return {
        content: [{ type: 'text', text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  },
);

// --- get_unread ---
server.tool(
  'get_unread',
  `Get unread incoming messages across all conversations.
Uses the "read horizon" model - replying marks prior messages as seen.`,
  {
    limit: z
      .number()
      .optional()
      .default(30)
      .describe('Max messages to return'),
  },
  async ({ limit }) => {
    try {
      const rows = await getUnread(limit);

      if (rows.length === 0) {
        return {
          content: [{ type: 'text', text: 'No unread messages.' }],
        };
      }

      const lines = ['# Unread Messages\n'];
      let currentSender: string | null = null;

      for (const row of rows) {
        if (row.sender !== currentSender) {
          if (currentSender) lines.push('');
          lines.push(`**${row.sender}**`);
          currentSender = row.sender;
        }
        const time = row.received_at
          ? new Date(row.received_at).toISOString().slice(5, 16).replace('T', ' ')
          : '?';
        const msg = row.message || '(no content)';
        lines.push(`  [${time}] ${msg}`);
      }

      return { content: [{ type: 'text', text: lines.join('\n') }] };
    } catch (err: any) {
      return {
        content: [{ type: 'text', text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  },
);

// --- Main ---
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[INFO][sms-mcp] Server started');
}

process.on('SIGINT', async () => {
  await shutdown();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await shutdown();
  process.exit(0);
});

main().catch((err) => {
  console.error('[ERROR][sms-mcp] Fatal:', err);
  process.exit(1);
});
