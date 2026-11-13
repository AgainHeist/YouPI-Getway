# Unified website

Run locally with Node 22.13+:

```sh
npm install
YOUPI_MODE=localhost YOUPI_DEMO_MODE=true npm run start:web
```

The site listens on port 3080 (override with `PORT`). `npm run build:web` creates the static Vercel assets in `dist-web`.

## Important: demo only on Vercel

The Vercel deployment is an **isolated public demo**, not a live payment gateway. Its SQLite database and generated secrets are stored in ephemeral function storage; instances do not share state and can reset at any time. Checkout, admin, wallet, and webhooks may therefore not work reliably across requests. Do not send real money or enter real customer information. `YOUPI_DEMO_MODE=true` publicly exposes an admin unlock and simulated payment/OTP flows: never use this mode with real merchants, real credentials or a production database. The default is off; enable it only in an isolated demo.

For actual payments use a persistent, shared database and a suitable always-on hosting setup for the gateway and observers, configure secure secrets and HTTPS, disable demo mode, and review the repository's deployment and security documentation before going live.
