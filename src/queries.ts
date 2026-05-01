import { query, queryOne, execute } from '@versedhand/common';

export async function getConversations() {
  return query(`
    WITH last_outgoing AS (
      SELECT phone_number, MAX(received_at) as last_sent_at
      FROM sms_messages WHERE direction = 'outgoing'
      GROUP BY phone_number
    ),
    conversation_stats AS (
      SELECT
        s.phone_number,
        MAX(s.received_at) as last_activity,
        COUNT(*) FILTER (
          WHERE s.direction = 'incoming' AND s.read_at IS NULL
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
  `);
}

export async function getThread(phone: string, limit: number = 50) {
  return query(
    `SELECT direction, message, received_at, read_at
     FROM sms_messages
     WHERE phone_number = $1
     ORDER BY received_at DESC
     LIMIT $2`,
    [phone, limit],
  );
}

export async function getUnread(limit: number = 30) {
  return query(
    `WITH last_outgoing AS (
       SELECT phone_number, MAX(received_at) as last_sent_at
       FROM sms_messages WHERE direction = 'outgoing'
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
     LIMIT $1`,
    [limit],
  );
}

export async function markRead(phone: string) {
  // Short codes are stored without +1 prefix (e.g. "44884" not "+144884")
  // Strip +1 prefix if the remaining digits are 5-6 chars (short code length)
  let normalized = phone;
  if (phone.startsWith('+1') && phone.length <= 8) {
    normalized = phone.slice(2);
  }
  return execute(
    `UPDATE sms_messages
     SET read_at = NOW(), status = 'read'
     WHERE phone_number = $1 AND read_at IS NULL`,
    [normalized],
  );
}

export async function getContactName(phone: string): Promise<string> {
  const row = await queryOne(
    'SELECT name FROM contacts WHERE phone_number = $1',
    [phone],
  );
  return row?.name ?? phone;
}

export async function insertOutgoingSms(
  messageId: string,
  phone: string,
  message: string,
) {
  return execute(
    `INSERT INTO sms_messages
     (message_id, direction, phone_number, message, received_at, source)
     VALUES ($1, 'outgoing', $2, $3, NOW(), 'phone')`,
    [messageId, phone, message],
  );
}
