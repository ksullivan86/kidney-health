/* Kidney Diet Log — the iPhone app with a server both ways: "N to review" (design note 39 §8.6, plan step 8).

   While a row waits for the person in Settings → This device → Your server (js/mock/server_changes.js `items`), or the first sync's
   profile card waits (js/mock/server_account.js `card`), the header's sync badge says "N to review", and pressing it opens that
   list. Today marks such an entry "needs review" (js/views/today.js asks `needsReview`). Nothing is decided here: the cards in
   Settings hold both copies and the person's choice. Device mode only; the web app's own badge (js/offline.js) is untouched. */
(() => {
  'use strict';
  const KH = window.KH;
  if (!KH.flags || KH.flags.DEVICE !== true) return;
  const { $ } = KH;
  const C = () => (KH.mock && KH.mock.serverChanges) || null;
  const P = () => (KH.mock && KH.mock.serverAccount) || null;

  function count() {
    let n = 0;
    try { const s = C() ? C().status() : null; if (s && s.active) n += s.review; } catch (e) { /* nothing to count yet */ }
    try { const a = P() ? P().status() : null; if (a && a.card) n += 1; } catch (e) { /* nothing to count yet */ }
    return n;
  }
  function render() {
    const badge = $('#sync-badge');
    if (!badge) return;
    const n = count();
    if (!n) {
      if (badge.dataset.review) { badge.hidden = true; delete badge.dataset.review; badge.classList.remove('failed'); }
      return;
    }
    badge.hidden = false;
    badge.dataset.review = String(n);
    badge.classList.add('failed');
    $('#sync-badge-text').textContent = `${n} to review`;
    $('#sync-badge-short').textContent = String(n);
    const long = n === 1 ? 'One change needs your choice: your iPhone and your server differ.' : `${n} changes need your choice: your iPhone and your server differ.`;
    badge.setAttribute('aria-label', `${long} Open Settings, This device.`);
    badge.title = long;
  }
  // Opens Settings → This device and moves to the cards (Settings draws its sections one by one, so wait for them).
  function open() {
    KH.router.show('settings');
    const until = Date.now() + 4000;
    const go = () => {
      const head = $('#set-server-profile-h') || $('#set-server-review-h');
      if (!head) { if (Date.now() < until) setTimeout(go, 80); return; }
      head.tabIndex = -1;
      head.scrollIntoView({ block: 'start' });
      head.focus({ preventScroll: true });
    };
    setTimeout(go, 0);
  }
  // Whether a row of this kind and ID waits in the review.
  function needsReview(kind, id) { try { return !!(id && C() && C().needsReview(kind, id)); } catch (e) { return false; } }

  const badge = $('#sync-badge');
  if (badge) badge.addEventListener('click', () => { if (badge.dataset.review) open(); });
  if (C()) C().subscribe(render);
  if (P()) P().subscribe(render);
  render();

  KH.serverReview = { render, open, needsReview, count };
})();
