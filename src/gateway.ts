function getEnvOrDie(name: string): string {
  const val = process.env[name];
  if (!val) throw new Error(`Missing required env var: ${name}`);
  return val;
}

const SMS_GATEWAY_URL = getEnvOrDie('SMS_GATEWAY_URL');
const SMS_GATEWAY_USER = getEnvOrDie('SMS_GATEWAY_USER');
const SMS_GATEWAY_PASS = getEnvOrDie('SMS_GATEWAY_PASS');

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
