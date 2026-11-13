(function () {
  'use strict';

  var selectedAmount = 1.00;
  var activeCodeTab = 'html';

  var CODE_SNIPPETS = {
    html: [
      '<!-- 1. Include Official YOUPI PG One-Script SDK -->',
      '<script',
      '  src="{{ORIGIN}}/youpi.js"',
      '  data-youpi-key="00000000-0000-0000-0000-000000000001"',
      '  data-currency="INR">',
      '</script>',
      '',
      '<!-- 2. Zero-JS Checkout Trigger Button -->',
      '<button',
      '  data-youpi-pay',
      '  data-order-id="ORD-2026-1001"',
      '  data-amount="499.00"',
      '  data-customer-name="Aarav Sharma"',
      '  data-customer-phone="9876543210"',
      '  data-success-url="/order-success">',
      '  Pay ₹499 via UPI (0% Fee)',
      '</button>'
    ].join('\n'),

    react: [
      '// Programmatic Checkout for React / Next.js / Vue / Svelte',
      'export async function handleCheckout(cart) {',
      '  window.Youpi.pay({',
      '    order_id: `ORD-${Date.now()}`,',
      '    amount: cart.totalRupees,',
      '    currency: "INR",',
      '    name: "My Sovereign Store",',
      '    description: "Instant Direct-to-Bank UPI Order",',
      '    customer: {',
      '      name: cart.customerName,',
      '      email: cart.customerEmail,',
      '      phone: cart.customerPhone',
      '    },',
      '    handler(result) {',
      '      console.log("UI Payment Confirmed (Verify Webhook on Server!):", result);',
      '    }',
      '  });',
      '}'
    ].join('\n'),

    webhook: [
      "import crypto from 'node:crypto';",
      "import express from 'express';",
      '',
      'const app = express();',
      '',
      '// CRITICAL: Verify HMAC-SHA256 over RAW unparsed request bytes!',
      "app.post('/api/webhook', express.raw({ type: 'application/json' }), (req, res) => {",
      "  const signature = String(req.headers['x-gateway-signature'] || '');",
      "  const expected = 'sha256=' + crypto",
      "    .createHmac('sha256', process.env.YOUPI_WEBHOOK_SECRET)",
      '    .update(req.body)',
      "    .digest('hex');",
      '',
      '  if (signature.length !== expected.length ||',
      '      !crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) {',
      "    return res.status(401).json({ error: 'Invalid signature' });",
      '  }',
      '',
      "  const event = JSON.parse(req.body.toString('utf8'));",
      "  if (event.event === 'SUCCESS' && event.method === 'UPI') {",
      '    // Fulfill order idempotently using event.orderId & event.utr',
      '  }',
      '  res.json({ received: true });',
      '});'
    ].join('\n'),

    curl: [
      '# Create a server-authoritative payment session via REST API',
      'curl -X POST "{{ORIGIN}}/api/v1/payments" \\',
      '  -H "Content-Type: application/json" \\',
      '  -d \'{',
      '    "orderId": "ORD-API-9001",',
      '    "amount": "249.00",',
      '    "currency": "INR",',
      '    "description": "Pro Subscription Plan",',
      '    "metadata": { "plan": "pro_annual" }',
      '  }\''
    ].join('\n')
  };

  function formatINR(num, decimals) {
    var d = typeof decimals === 'number' ? decimals : 2;
    return '₹' + Number(num || 0).toLocaleString('en-IN', {
      minimumFractionDigits: d,
      maximumFractionDigits: d
    });
  }

  function logEvent(message) {
    var box = document.getElementById('liveEventConsole');
    if (!box) return;
    var ts = new Date().toLocaleTimeString('en-IN', { hour12: false });
    var line = document.createElement('div');
    line.textContent = '[' + ts + '] ' + message;
    box.insertBefore(line, box.firstChild);
  }

  function syncSandboxAmountUI() {
    var disp = document.getElementById('sandboxAmountBig');
    var btnAmt = document.getElementById('sandboxBtnAmt');
    var fmt = formatINR(selectedAmount, 2);
    if (disp) disp.textContent = fmt;
    if (btnAmt) btnAmt.textContent = fmt;

    document.querySelectorAll('[data-amt-chip]').forEach(function (chip) {
      var val = parseFloat(chip.getAttribute('data-amt-chip'));
      chip.classList.toggle('active', Math.abs(val - selectedAmount) < 0.001);
    });
  }

  function initSandboxControls() {
    document.querySelectorAll('[data-amt-chip]').forEach(function (chip) {
      chip.addEventListener('click', function () {
        selectedAmount = parseFloat(chip.getAttribute('data-amt-chip')) || 1;
        var inp = document.getElementById('sandboxCustomAmount');
        if (inp) inp.value = selectedAmount.toFixed(2);
        syncSandboxAmountUI();
      });
    });

    var customInput = document.getElementById('sandboxCustomAmount');
    if (customInput) {
      customInput.addEventListener('input', function () {
        var v = parseFloat(customInput.value);
        if (isFinite(v) && v >= 1 && v <= 100000) {
          selectedAmount = v;
          syncSandboxAmountUI();
        }
      });
    }

    var launchBtns = document.querySelectorAll('[data-launch-sandbox]');
    launchBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        launchLiveCheckout(btn);
      });
    });

    window.addEventListener('youpi:payment:success', function (ev) {
      var d = (ev && ev.detail) || {};
      logEvent('SUCCESS order=' + (d.order_id || '-') + ' utr=' + (d.utr || 'VERIFIED') + ' mode=' + (d.payment_mode || 'UPI'));
      refreshPlatformStatus();
    });

    window.addEventListener('youpi:payment:cancelled', function (ev) {
      var d = (ev && ev.detail) || {};
      logEvent('CANCELLED order=' + (d.order_id || '-') + ' — slot released cleanly');
      refreshPlatformStatus();
    });

    window.addEventListener('youpi:payment:expired', function (ev) {
      var d = (ev && ev.detail) || {};
      logEvent('EXPIRED order=' + (d.order_id || '-'));
      refreshPlatformStatus();
    });
  }

  async function launchLiveCheckout(triggerBtn) {
    if (!window.Youpi || typeof window.Youpi.pay !== 'function') {
      logEvent('Error: youpi.js SDK not loaded yet.');
      return;
    }

    var nameEl = document.getElementById('sandboxCustomerName');
    var custName = (nameEl && nameEl.value ? nameEl.value.trim() : '') || 'Demo Merchant Buyer';
    var orderId = 'WEB-DEMO-' + Date.now();
    var oldText = triggerBtn ? triggerBtn.innerHTML : '';

    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.textContent = 'Allocating Gateway Slot...';
    }
    logEvent('Creating session ' + orderId + ' for ' + formatINR(selectedAmount, 2) + '...');

    try {
      await window.Youpi.pay({
        apiUrl: window.location.origin,
        portalUrl: window.location.origin,
        order_id: orderId,
        amount: selectedAmount.toFixed(2),
        currency: 'INR',
        name: 'YOUPI PG Live Sandbox',
        description: 'Interactive Website Checkout Test',
        customer: {
          name: custName
        },
        metadata: {
          source: 'youpi-official-website'
        },
        handler: function (res) {
          logEvent('Modal confirmed! UTR: ' + (res.utr || 'Instant Verified'));
        },
        onClose: function () {
          if (triggerBtn) {
            triggerBtn.disabled = false;
            triggerBtn.innerHTML = oldText;
          }
          refreshPlatformStatus();
        }
      });
    } catch (err) {
      logEvent('Checkout error: ' + (err && err.message ? err.message : String(err)));
    } finally {
      if (triggerBtn) {
        triggerBtn.disabled = false;
        triggerBtn.innerHTML = oldText;
      }
    }
  }

  function initFeeCalculator() {
    var volSlider = document.getElementById('calcVolumeSlider');
    var feeSlider = document.getElementById('calcAggregatorFeeSlider');
    if (!volSlider || !feeSlider) return;

    function updateCalc() {
      var monthlyGmv = Number(volSlider.value) || 500000;
      var mdrPct = Number(feeSlider.value) || 2.0;
      var effectivePctWithGst = mdrPct * 1.18; // +18% GST on gateway fee
      var monthlyAggregatorCost = Math.round(monthlyGmv * (effectivePctWithGst / 100));
      var annualSavings = monthlyAggregatorCost * 12;

      var elGmv = document.getElementById('calcGmvVal');
      var elMdr = document.getElementById('calcMdrVal');
      var elMonthly = document.getElementById('calcMonthlyFee');
      var elAnnual = document.getElementById('calcAnnualSavings');

      if (elGmv) elGmv.textContent = formatINR(monthlyGmv, 0) + ' / mo';
      if (elMdr) elMdr.textContent = mdrPct.toFixed(1) + '% + 18% GST (' + effectivePctWithGst.toFixed(2) + '%)';
      if (elMonthly) elMonthly.textContent = formatINR(monthlyAggregatorCost, 0) + ' / month lost to aggregator';
      if (elAnnual) elAnnual.textContent = formatINR(annualSavings, 0);
    }

    volSlider.addEventListener('input', updateCalc);
    feeSlider.addEventListener('input', updateCalc);
    updateCalc();
  }

  function initCodePlayground() {
    var codeEl = document.getElementById('codeSnippetOutput');
    var copyBtn = document.getElementById('btnCopyCode');
    if (!codeEl) return;

    function renderTab(tab) {
      activeCodeTab = tab;
      var raw = CODE_SNIPPETS[tab] || CODE_SNIPPETS.html;
      codeEl.textContent = raw.replaceAll('{{ORIGIN}}', window.location.origin);
      document.querySelectorAll('[data-code-tab]').forEach(function (btn) {
        btn.classList.toggle('active', btn.getAttribute('data-code-tab') === tab);
      });
    }

    document.querySelectorAll('[data-code-tab]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        renderTab(btn.getAttribute('data-code-tab'));
      });
    });

    if (copyBtn) {
      copyBtn.addEventListener('click', function () {
        var text = codeEl.textContent || '';
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            copyBtn.textContent = '✓ Copied!';
            setTimeout(function () { copyBtn.textContent = 'Copy Snippet'; }, 1800);
          });
        }
      });
    }

    renderTab('html');
  }

  function refreshPlatformStatus() {
    fetch('/api/platform/status')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data) return;
        var vpaEl = document.getElementById('liveVpaChip');
        var statusText = document.getElementById('liveStatusText');
        var metricSessions = document.getElementById('metricTotalSessions');
        var slotState = document.getElementById('sandboxSlotBadge');

        if (vpaEl && data.receivingVpa) {
          vpaEl.textContent = 'VPA: ' + data.receivingVpa;
        }
        if (statusText) {
          var qText = data.isSlotBusy ? ('1 Active • ' + (data.queueDepth || 0) + ' Queued') : 'Slot Free & Ready';
          statusText.textContent = 'Gateway Online • ' + qText + ' • SQLite WAL';
        }
        if (metricSessions && typeof data.totalSessions === 'number') {
          metricSessions.textContent = String(data.totalSessions);
        }
        if (slotState) {
          slotState.textContent = data.isSlotBusy ? 'FIFO Slot Active' : 'Slot Ready · 0ms Queue';
        }
      })
      .catch(function () {});
  }

  function initMobileDrawer() {
    var toggle = document.getElementById('mobileMenuToggle');
    var drawer = document.getElementById('mobileNavDrawer');
    if (!toggle || !drawer) return;
    toggle.addEventListener('click', function () {
      drawer.classList.toggle('open');
    });
    drawer.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        drawer.classList.remove('open');
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initMobileDrawer();
    initSandboxControls();
    initFeeCalculator();
    initCodePlayground();
    refreshPlatformStatus();
  });
})();
