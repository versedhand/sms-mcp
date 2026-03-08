const SMS_GATEWAY_URL =
  process.env.SMS_GATEWAY_URL || 'http://100.83.238.68:8080';
const SMS_GATEWAY_USER = process.env.SMS_GATEWAY_USER || 'sms';
const SMS_GATEWAY_PASS = process.env.SMS_GATEWAY_PASS || 'Lt9VJGAk';

export async function sendViaGateway(
  phone: string,
  message: string,
): Promise<{ id?: string; [key: string]: any }> {
  const auth = Buffer.from(
    `${SMS_GATEWAY_USER}:${SMS_GATEWAY_PASS}`,
  ).toString('base64');

  const response = await fetch(`${SMS_GATEWAY_URL}/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Basic ${auth}`,
    },
    body: JSON.stringify({ message, phoneNumbers: [phone] }),
    signal: AbortSignal.timeout(30000),
  });

  if (!response.ok) {
    throw new Error(`Gateway error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}
