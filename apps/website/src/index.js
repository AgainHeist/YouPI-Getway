import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebsiteServer } from './server.js';

export { WebsiteServer } from './server.js';

/**
 * Boots the public website + documentation portal.
 * @param {number|null} [port]
 * @param {ConstructorParameters<typeof WebsiteServer>[0]} [options]
 */
export function startWebsite(port = null, options = {}) {
  const finalPort = port || Number(process.env.WEBSITE_PORT || 4000);
  const website = new WebsiteServer(options);
  const rawServer = website.createServer();

  // Same convention as the other YOUPI services: loopback by default, overridable for
  // containerised / preview deployments where the proxy is not on this host.
  const bindHost = process.env.YOUPI_BIND_HOST || '127.0.0.1';

  return new Promise(resolve => {
    const instance = rawServer.listen(finalPort, bindHost, () => {
      console.log(`[Website] Marketing site & docs portal on http://localhost:${finalPort}`);
      resolve({
        port: finalPort,
        server: instance,
        close: () => new Promise(done => instance.close(done))
      });
    });
  });
}

// Auto-run when executed directly.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  startWebsite();
}
