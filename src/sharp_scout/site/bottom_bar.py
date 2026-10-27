"""Fixed bottom navigation + My card slip — shared across all GitHub Pages."""

from __future__ import annotations

from typing import Literal

from sharp_scout.site.site_nav import nba_nav_label

BottomBarActive = Literal["plays", "results", "props", "comments", "board"]

# Height of the fixed bar (px), used for body padding and slip positioning.
BOTTOM_BAR_PX = 62


def bottom_bar_css() -> str:
    return f"""
  body.ss-bottom-bar {{ padding-bottom: calc({BOTTOM_BAR_PX}px + env(safe-area-inset-bottom, 0px) + 12px); }}
  .lp-badge {{ display: inline-block; min-width: 18px; padding: 0 5px; border-radius: 9px; background: #15803d;
    color: #fff; font-size: 11px; font-weight: 700; margin-left: 2px; }}
  .lp-bbar {{ position: fixed; left: 0; right: 0; bottom: 0; background: #fff; border-top: 1px solid var(--color-border);
    display: flex; z-index: 600; padding-bottom: env(safe-area-inset-bottom); }}
  .lp-bbar a, .lp-bbar button {{ flex: 1; text-align: center; padding: 9px 0 11px; font-size: 12px;
    color: var(--color-text-muted); text-decoration: none; border: 0; background: #fff; cursor: pointer;
    font-family: var(--font-sans); }}
  .lp-bbar .on {{ color: var(--color-navy); font-weight: 700; }}
  .lp-bbar .i {{ display: block; font-size: 18px; line-height: 1.1; }}
  .lp-more-panel {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 800; }}
  .lp-more-panel.open {{ display: block; }}
  .lp-more-sheet {{ position: absolute; left: 0; right: 0; bottom: 0; background: #fff; border-radius: 16px 16px 0 0;
    padding: 16px 18px calc(24px + env(safe-area-inset-bottom)); max-height: 70vh; overflow: auto; }}
  .lp-more-sheet a {{ display: block; padding: 12px 0; color: var(--color-navy); text-decoration: none; font-weight: 600;
    border-bottom: 1px solid var(--color-border); }}
  .lp-slip-overlay {{ display: none; }}
  .lp-slip-overlay.open {{ display: block; position: fixed; left: 0; right: 0; bottom: {BOTTOM_BAR_PX}px; background: #fff;
    border-radius: 18px 18px 0 0; box-shadow: 0 -8px 30px rgba(0,0,0,.18); padding: 18px; z-index: 700;
    max-height: min(70vh, calc(100vh - {BOTTOM_BAR_PX}px - 24px)); overflow: auto; }}
  .lp-slip-overlay h2 {{ font-size: 18px; margin: 0 0 4px; font-family: var(--font-serif); }}
  .lp-slip-sub {{ font-size: 13px; color: var(--color-text-muted); margin-bottom: 10px; }}
  .lp-slip-overlay ul {{ list-style: none; margin: 0; padding: 0; }}
  .lp-slip-overlay li {{ display: flex; justify-content: space-between; gap: 10px; padding: 10px 0;
    border-top: 1px solid var(--color-border); font-size: 15px; }}
  .lp-slip-overlay li small {{ display: block; color: var(--color-text-muted); font-size: 13px; }}
  .lp-slip-overlay li button {{ border: 0; background: none; color: #b91c1c; cursor: pointer; font-size: 13px; }}
  .lp-slip-overlay .lp-copy {{ width: 100%; margin-top: 10px; border: 1px solid var(--color-navy); background: #fff;
    color: var(--color-navy); border-radius: 12px; padding: 12px; font-weight: 700; cursor: pointer; font-family: var(--font-sans); }}
  @media (min-width: 900px) {{
    .lp-bbar {{
      max-width: min(1180px, 100%);
      margin: 0 auto;
      left: 0; right: 0;
      border-left: 1px solid var(--color-border);
      border-right: 1px solid var(--color-border);
      border-radius: 14px 14px 0 0;
      box-shadow: 0 -4px 24px rgba(16, 24, 40, .08);
    }}
    .lp-bbar a, .lp-bbar button {{ font-size: 13px; padding: 11px 0 13px; }}
    .lp-slip-overlay.open {{
      left: 50%;
      transform: translateX(-50%);
      max-width: min(480px, calc(100% - 32px));
      border-radius: 16px;
      bottom: calc({BOTTOM_BAR_PX}px + 12px);
      box-shadow: 0 12px 40px rgba(0,0,0,.2);
    }}
  }}
"""


def _tab_class(active: BottomBarActive, tab: str) -> str:
    if tab == "results":
        on = active in ("results", "board")
    else:
        on = active == tab
    return ' class="on"' if on else ""


def render_bottom_bar(*, active: BottomBarActive) -> str:
    """Fixed bottom nav. ``active`` highlights Plays, Results, Props, or Comments when applicable."""
    comments_em = ' style="font-weight:800"' if active == "comments" else ""
    props_em = ' style="font-weight:800"' if active == "props" else ""
    return f"""
<nav class="lp-bbar" aria-label="Site">
  <a{_tab_class(active, "plays")} href="index.html"><span class="i">★</span>Plays</a>
  <button type="button" id="lp-bbar-slip"><span class="i">🧾</span>My card <span class="lp-badge" id="lp-bbar-count">0</span></button>
  <a{_tab_class(active, "results")} href="board.html#tab-plays"><span class="i">📈</span>Results</a>
  <button type="button" id="lp-more-open"><span class="i">☰</span>More</button>
</nav>
<div class="lp-more-panel" id="lp-more-panel">
  <div class="lp-more-sheet">
    <button type="button" id="lp-more-close" style="float:right;border:0;background:none;font-size:22px;cursor:pointer">×</button>
    <h3 style="margin-top:0">More</h3>
    <a href="board.html">Full board</a>
    <a href="board.html#tab-plays">NFL board</a>
    <a href="board.html#tab-cfb">College board</a>
    <a href="board.html#tab-guide">How it works</a>
    <a href="comments.html"{comments_em}>Comments</a>
    <a href="props.html"{props_em}>NFL Props</a>
    <a href="nba.html">{nba_nav_label()}</a>
  </div>
</div>
"""


def render_slip_overlay() -> str:
    """Floating My card panel (used on board / props / comments; landing uses inline sidebar too)."""
    return """
<aside class="lp-slip-overlay" id="lp-slip-overlay" aria-label="My card">
  <h2>My card <span class="lp-badge" id="lp-slip-overlay-count">0</span></h2>
  <div class="lp-slip-sub">Saved on this phone or computer only.</div>
  <ul id="lp-slip-overlay-list"></ul>
  <button type="button" class="lp-copy" id="lp-copy-btn-overlay">Copy my card</button>
</aside>
"""


BOTTOM_BAR_SCRIPT = """
<script>
(function () {
  var STORAGE = 'ssSlip';

  function normalizeMeta(v) {
    if (!v || v === 1) return {};
    if (typeof v === 'object') return v;
    return {};
  }

  function loadSlip() {
    var m = new Map();
    try {
      JSON.parse(localStorage.getItem(STORAGE) || '[]').forEach(function (pair) {
        if (!pair || !pair.length) return;
        m.set(String(pair[0]), normalizeMeta(pair[1]));
      });
    } catch (e) { /* ignore corrupt storage */ }
    return m;
  }

  var slip = loadSlip();

  function cardMetaFromDom(card) {
    var pick = card.querySelector('.lp-pick');
    var game = card.querySelector('.lp-game');
    var kick = card.querySelector('.lp-matchup span:last-child');
    var price = card.querySelector('.lp-price b');
    return {
      line: pick ? pick.innerText.replace(/\\s+/g, ' ').trim() : '',
      game: game ? game.textContent.trim() : '',
      kick: kick ? kick.textContent.trim() : '',
      price: price ? price.textContent.trim() : ''
    };
  }

  function metaForId(id) {
    var card = document.querySelector('.lp-card[data-play-id="' + id + '"]');
    if (card) return cardMetaFromDom(card);
    return normalizeMeta(slip.get(id));
  }

  function persistSlip() {
    var arr = [];
    slip.forEach(function (meta, id) {
      arr.push([id, metaForId(id)]);
    });
    localStorage.setItem(STORAGE, JSON.stringify(arr));
  }

  function renderList(listEl) {
    if (!listEl) return;
    var n = slip.size;
    if (!n) {
      listEl.innerHTML = '<li class="lp-slip-none">Nothing saved yet. Tap <b>Add to my card</b> on a play.</li>';
      return;
    }
    listEl.innerHTML = '';
    slip.forEach(function (_, id) {
      var meta = metaForId(id);
      var li = document.createElement('li');
      li.innerHTML = '<div><strong>' + (meta.line || 'Saved play') + '</strong>' +
        (meta.price ? ' (' + meta.price + ')' : '') +
        '<small>' + (meta.game || '') + (meta.game && meta.kick ? ' · ' : '') + (meta.kick || '') + '</small></div>' +
        '<button type="button" data-rm="' + id + '">Remove</button>';
      listEl.appendChild(li);
    });
  }

  function syncSlipUi() {
    var n = slip.size;
    ['lp-slip-count', 'lp-bbar-count', 'lp-slip-overlay-count'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.textContent = String(n);
    });
    renderList(document.getElementById('lp-slip-list'));
    renderList(document.getElementById('lp-slip-overlay-list'));
    persistSlip();
    document.querySelectorAll('.lp-card').forEach(function (card) {
      var id = card.getAttribute('data-play-id');
      var btn = card.querySelector('.lp-add');
      if (!btn || !id) return;
      var on = slip.has(id);
      btn.classList.toggle('added', on);
      btn.textContent = on ? '✓ On my card' : '+ Add to my card';
    });
  }

  function toggleSlipPanel() {
    var overlay = document.getElementById('lp-slip-overlay');
    var inline = document.getElementById('lp-slip');
    if (window.matchMedia('(min-width: 900px)').matches && inline) {
      inline.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (overlay) overlay.classList.remove('open');
      return;
    }
    if (overlay) overlay.classList.toggle('open');
    else if (inline) inline.classList.toggle('open');
  }

  document.addEventListener('click', function (e) {
    var add = e.target.closest('.lp-add');
    if (add) {
      var id = add.getAttribute('data-play-id') || (add.closest('.lp-card') && add.closest('.lp-card').getAttribute('data-play-id'));
      if (!id) return;
      if (slip.has(id)) slip.delete(id);
      else {
        var card = add.closest('.lp-card');
        slip.set(id, card ? cardMetaFromDom(card) : {});
      }
      syncSlipUi();
      return;
    }
    var rm = e.target.closest('[data-rm]');
    if (rm) {
      slip.delete(rm.getAttribute('data-rm'));
      syncSlipUi();
      return;
    }
    if (e.target.closest('#lp-bbar-slip')) {
      e.preventDefault();
      toggleSlipPanel();
      return;
    }
    if (e.target.closest('#lp-copy-btn') || e.target.closest('#lp-copy-btn-overlay')) {
      var list = document.getElementById('lp-slip-list') || document.getElementById('lp-slip-overlay-list');
      if (list && navigator.clipboard) navigator.clipboard.writeText(list.innerText);
      return;
    }
    if (e.target.closest('#lp-more-open')) {
      e.preventDefault();
      document.getElementById('lp-more-panel').classList.add('open');
      return;
    }
    if (e.target.closest('#lp-more-close') || e.target.closest('#lp-more-panel') === e.target) {
      document.getElementById('lp-more-panel').classList.remove('open');
    }
    if (e.target.closest('#lp-slip-overlay') && !e.target.closest('button') && !e.target.closest('[data-rm]')) {
      /* keep panel open when clicking inside */
    }
  });

  window.addEventListener('storage', function (ev) {
    if (ev.key === STORAGE) {
      slip = loadSlip();
      syncSlipUi();
    }
  });

  syncSlipUi();
  window.ssSlipSync = syncSlipUi;
})();
</script>
"""
