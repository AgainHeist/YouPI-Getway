/**
 * YOUPI PG V2 — Interactive Cloud Sandbox Bridge
 * Loaded only when YOUPI_DEMO_MODE=true on unified web deployments.
 * Provides:
 *  1. 1-Tap Sandbox OTP display & auto-fill inside /checkout/:id when WhatsApp socket is unpaired.
 *  2. 1-Tap Realistic Bank SMS Credit Simulator inside /checkout/:id that feeds genuine
 *     SMS text through the server's ObservationNormalizer -> AttributionEngine pipeline.
 *  3. 1-Tap Demo Admin Unlock + Back-to-Website navigation bar on /admin & /store.
 */
(function () {
  'use strict';

  var pathname = window.location.pathname || '/';

  // ---------------------------------------------------------------------------
  // A. CHECKOUT PORTAL SANDBOX ENHANCEMENTS (/checkout/:id)
  // ---------------------------------------------------------------------------
  if (pathname.indexOf('/checkout/') === 0) {
    var capturedOtp = null;
    var origFetch = window.fetch.bind(window);

    window.fetch = function (input, init) {
      var urlStr = typeof input === 'string' ? input : (input && input.url ? input.url : '');
      return origFetch(input, init).then(function (response) {
        if (urlStr.indexOf('/api/v1/customer/send-otp') !== -1) {
          response.clone().json().then(function (data) {
            if (data && data.devOtp) {
              capturedOtp = String(data.devOtp);
              renderDemoOtpBanner(capturedOtp);
            }
          }).catch(function () {});
        }
        return response;
      });
    };

    function renderDemoOtpBanner(otp) {
      var stepOtp = document.getElementById('authStepOtp');
      if (!stepOtp || !otp) return;

      var existing = document.getElementById('ypgSandboxOtpBanner');
      if (!existing) {
        existing = document.createElement('div');
        existing.id = 'ypgSandboxOtpBanner';
        existing.style.cssText =
          'margin:0 0 12px;padding:10px 12px;border-radius:10px;' +
          'background:linear-gradient(135deg,#ecfdf5,#d1fae5);border:1px solid #6ee7b7;' +
          'display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;' +
          'font-family:system-ui,-apple-system,sans-serif;box-shadow:0 2px 8px rgba(16,185,129,0.12);';
        var otpInputGroup = stepOtp.querySelector('.ypg-input-group');
        if (otpInputGroup && otpInputGroup.parentNode) {
          otpInputGroup.parentNode.insertBefore(existing, otpInputGroup);
        } else {
          stepOtp.insertBefore(existing, stepOtp.firstChild);
        }
      }

      existing.innerHTML = '';
      var left = document.createElement('div');
      left.style.cssText = 'font-size:12px;color:#065f46;line-height:1.35;';
      var badge = document.createElement('div');
      badge.style.cssText = 'font-weight:800;font-size:11px;text-transform:uppercase;letter-spacing:0.04em;color:#047857;';
      badge.textContent = 'Cloud Sandbox OTP Ready';
      var codeLine = document.createElement('div');
      codeLine.style.cssText = 'margin-top:2px;font-weight:600;';
      codeLine.textContent = 'Demo Code: ';
      var codeStrong = document.createElement('strong');
      codeStrong.style.cssText = 'font-family:ui-monospace,monospace;font-size:14px;letter-spacing:2px;background:#fff;padding:1px 6px;border-radius:5px;border:1px solid #a7f3d0;color:#064e3b;';
      codeStrong.textContent = otp;
      codeLine.appendChild(codeStrong);
      left.appendChild(badge);
      left.appendChild(codeLine);

      var fillBtn = document.createElement('button');
      fillBtn.type = 'button';
      fillBtn.textContent = '1-Tap Auto-Fill & Verify';
      fillBtn.style.cssText =
        'padding:7px 12px;border-radius:8px;border:0;background:#059669;color:#ffffff;' +
        'font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;box-shadow:0 2px 6px rgba(5,150,105,0.28);';
      fillBtn.addEventListener('click', function () {
        var inp = document.getElementById('authOtpInput');
        if (inp) {
          inp.value = otp;
          inp.dispatchEvent(new Event('input', { bubbles: true }));
        }
        var verifyBtn = document.getElementById('btnAuthVerifyOtp');
        if (verifyBtn) verifyBtn.click();
      });

      existing.appendChild(left);
      existing.appendChild(fillBtn);
    }

    function injectBankSmsSimulator() {
      var upiView = document.getElementById('viewUpiContent');
      if (!upiView || document.getElementById('ypgSandboxPayBar')) return;

      var paymentIdMatch = pathname.match(/^\/checkout\/([^/?#]+)/);
      var paymentId = paymentIdMatch ? decodeURIComponent(paymentIdMatch[1]) : '';
      if (!paymentId) return;

      var bar = document.createElement('div');
      bar.id = 'ypgSandboxPayBar';
      bar.style.cssText =
        'margin-top:12px;padding:11px 13px;border-radius:11px;' +
        'background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid #334155;' +
        'color:#f8fafc;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;' +
        'font-family:system-ui,-apple-system,sans-serif;box-shadow:0 6px 18px rgba(15,23,42,0.18);';

      var info = document.createElement('div');
      info.style.cssText = 'flex:1;min-width:170px;';
      var title = document.createElement('div');
      title.style.cssText = 'font-size:11.5px;font-weight:800;color:#34d399;letter-spacing:0.03em;text-transform:uppercase;';
      title.textContent = 'Live Sandbox Bank Observer';
      var sub = document.createElement('div');
      sub.style.cssText = 'font-size:11.5px;color:#cbd5e1;margin-top:2px;line-height:1.35;';
      sub.textContent = 'Test real HDFC UPI SMS parsing, UTR attribution & instant settlement:';
      info.appendChild(title);
      info.appendChild(sub);

      var simBtn = document.createElement('button');
      simBtn.type = 'button';
      simBtn.id = 'btnSandboxSimulateSms';
      simBtn.textContent = 'Simulate Bank SMS Credit';
      simBtn.style.cssText =
        'padding:8px 13px;border-radius:8px;border:0;' +
        'background:linear-gradient(135deg,#10b981,#059669);color:#04130e;' +
        'font-size:12px;font-weight:800;cursor:pointer;white-space:nowrap;transition:opacity 0.15s;';

      simBtn.addEventListener('click', function () {
        simBtn.disabled = true;
        simBtn.style.opacity = '0.7';
        simBtn.textContent = 'Injecting Bank SMS...';
        origFetch('/api/demo/simulate-payment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ paymentId: paymentId })
        })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
          .then(function (res) {
            if (res.ok && res.data && res.data.success) {
              simBtn.textContent = 'Verified UTR ' + (res.data.utr || '');
              simBtn.style.background = '#22c55e';
              if (typeof window.loadState === 'function') {
                window.loadState();
              }
            } else {
              simBtn.disabled = false;
              simBtn.style.opacity = '1';
              simBtn.textContent = 'Simulate Bank SMS Credit';
              if (typeof window.showOptionToast === 'function') {
                window.showOptionToast((res.data && res.data.error) || 'Complete mobile login first to activate slot.');
              }
            }
          })
          .catch(function () {
            simBtn.disabled = false;
            simBtn.style.opacity = '1';
            simBtn.textContent = 'Simulate Bank SMS Credit';
          });
      });

      bar.appendChild(info);
      bar.appendChild(simBtn);
      upiView.appendChild(bar);
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', injectBankSmsSimulator);
    } else {
      injectBankSmsSimulator();
    }
    return;
  }

  // ---------------------------------------------------------------------------
  // B. MERCHANT ADMIN HUB SANDBOX UNLOCK & HOME BAR (/admin)
  // ---------------------------------------------------------------------------
  if (pathname === '/admin' || pathname.indexOf('/admin/') === 0) {
    function injectAdminHelpers() {
      // 1. Add a subtle "<- Website Home" link in the header if not present
      if (!document.getElementById('ypgBackHomePill')) {
        var pill = document.createElement('a');
        pill.id = 'ypgBackHomePill';
        pill.href = '/';
        pill.textContent = '← YOUPI Home';
        pill.style.cssText =
          'position:fixed;bottom:16px;left:16px;z-index:99999;padding:8px 14px;border-radius:999px;' +
          'background:#0f766e;color:#ffffff;font-family:system-ui,sans-serif;font-size:12.5px;font-weight:700;' +
          'text-decoration:none;box-shadow:0 8px 24px rgba(15,118,110,0.35);border:1px solid rgba(255,255,255,0.2);';
        document.body.appendChild(pill);
      }

      // 2. Watch for the Admin Token prompt form and add a 1-Tap Demo Unlock button
      var forms = document.querySelectorAll('form');
      forms.forEach(function (box) {
        if (box.dataset.ypgUnlockBound) return;
        var h3 = box.querySelector('h3');
        var pwInput = box.querySelector('input[type="password"]');
        if (h3 && pwInput && h3.textContent && h3.textContent.indexOf('Admin token') !== -1) {
          box.dataset.ypgUnlockBound = '1';
          var demoBtn = document.createElement('button');
          demoBtn.type = 'button';
          demoBtn.textContent = '⚡ 1-Tap Demo Admin Unlock (Sandbox)';
          demoBtn.style.cssText =
            'width:100%;margin-top:8px;padding:10px;border-radius:8px;border:1px solid #10b981;' +
            'background:#ecfdf5;color:#065f46;font-weight:700;font-size:13px;cursor:pointer;';
          demoBtn.addEventListener('click', function () {
            demoBtn.disabled = true;
            demoBtn.textContent = 'Unlocking Demo Hub...';
            fetch('/api/demo/admin-unlock', { method: 'POST' })
              .then(function (r) { return r.json(); })
              .then(function (d) {
                if (d && d.token) {
                  pwInput.value = d.token;
                  box.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                } else {
                  demoBtn.textContent = 'Demo unlock disabled in strict mode';
                }
              })
              .catch(function () {
                demoBtn.disabled = false;
                demoBtn.textContent = '⚡ 1-Tap Demo Admin Unlock (Sandbox)';
              });
          });
          box.appendChild(demoBtn);
        }
      });
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', injectAdminHelpers);
    } else {
      injectAdminHelpers();
    }
    var obs = new MutationObserver(injectAdminHelpers);
    obs.observe(document.documentElement, { childList: true, subtree: true });
    return;
  }

  // ---------------------------------------------------------------------------
  // C. STORE / WALLET / HELP FLOATING RETURN PILL
  // ---------------------------------------------------------------------------
  function injectBackPill() {
    if (document.getElementById('ypgBackHomePill')) return;
    var nav = document.createElement('div');
    nav.id = 'ypgBackHomePill';
    nav.style.cssText =
      'position:fixed;bottom:16px;left:16px;z-index:9999;display:flex;gap:8px;align-items:center;' +
      'font-family:system-ui,-apple-system,sans-serif;';
    var homeLink = document.createElement('a');
    homeLink.href = '/';
    homeLink.textContent = '← YOUPI Website';
    homeLink.style.cssText =
      'padding:8px 14px;border-radius:999px;background:#0f172a;color:#f8fafc;font-size:12.5px;' +
      'font-weight:700;text-decoration:none;box-shadow:0 8px 24px rgba(15,23,42,0.28);border:1px solid #334155;';
    nav.appendChild(homeLink);
    document.body.appendChild(nav);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectBackPill);
  } else {
    injectBackPill();
  }
})();
