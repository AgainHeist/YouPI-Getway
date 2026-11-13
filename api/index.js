import { createUnifiedGatewayHandler } from '../apps/web-portal/src/gateway-handler.js';

export const config = {
  api: {
    bodyParser: false
  }
};

const handler = createUnifiedGatewayHandler();

export default async function vercelGatewayEntry(req, res) {
  try {
    await handler(req, res);
  } catch (err) {
    console.error('[Vercel Gateway Entry] Error:', err);
    if (!res.headersSent) {
      res.statusCode = 500;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(JSON.stringify({ error: 'Internal Gateway Error', message: err?.message || 'Unexpected error' }));
    }
  }
}
