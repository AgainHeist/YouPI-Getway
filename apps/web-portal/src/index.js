import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createUnifiedGatewayHandler, getUnifiedGatewayRuntime } from './gateway-handler.js';

export async function startWebPortal(port = Number(process.env.PORT || 3080), options = {}) {
  const host = options.host || process.env.YOUPI_BIND_HOST || '0.0.0.0';
  const runtime = await getUnifiedGatewayRuntime(options);
  const handler = createUnifiedGatewayHandler(options);
  const server = http.createServer((req, res) => {
    handler(req, res).catch(err => {
      console.error('[WebPortal] Unhandled request error:', err);
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal Server Error' }));
      }
    });
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => resolve());
  });

  const addr = server.address();
  const actualPort = typeof addr === 'object' && addr ? addr.port : port;

  return {
    port: actualPort,
    host,
    server,
    runtime,
    async close() {
      await new Promise(r => server.close(() => r()));
      await runtime.close();
    }
  };
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const targetPort = Number(process.env.PORT || 3080);
  startWebPortal(targetPort)
    .then(instance => {
      console.log('====================================================');
      console.log(`🟢 YOUPI PG V2 — UNIFIED WEBSITE & GATEWAY ONLINE`);
      console.log(`• Bound Address:  http://${instance.host}:${instance.port}`);
      console.log(`• Homepage:       http://localhost:${instance.port}/`);
      console.log(`• Demo Store:     http://localhost:${instance.port}/store`);
      console.log(`• Merchant Admin: http://localhost:${instance.port}/admin`);
      console.log(`• Docs Hub:       http://localhost:${instance.port}/docs`);
      console.log(`• API Explorer:   http://localhost:${instance.port}/api-docs`);
      console.log('====================================================');
    })
    .catch(err => {
      console.error('Failed to start YOUPI Unified Website:', err);
      process.exit(1);
    });
}
