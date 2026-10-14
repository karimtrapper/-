/* Wave 4a display helpers. Only text and presentation classes are changed;
   input values, select options, event handlers and API payloads are untouched. */
(function () {
  'use strict';
  const GROUP_SPACES = /[\u00a0\u202f]/g;
  const moneyFormatter = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const integerFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

  function formatDisplayMoney(value, currency, digits) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    const code = String(currency || '').toUpperCase();
    const places = digits == null ? (code === 'THB' || currency === '฿' ? (Number.isInteger(n) ? 0 : 2) : 2) : digits;
    const formatter = places === 0 ? integerFormatter : moneyFormatter;
    const number = formatter.format(n).replace(GROUP_SPACES, ' ');
    if (code === 'USD' || currency === '$') return '$' + number;
    const suffix = code === 'RUB' ? '₽' : code === 'THB' ? '฿' : currency;
    return suffix ? number + ' ' + suffix : number;
  }
  window.formatDisplayMoney = formatDisplayMoney;

  function parseDisplayNumber(raw) {
    let s = raw.replace(GROUP_SPACES, ' ').replace(/\s/g, '');
    const comma = s.lastIndexOf(','), dot = s.lastIndexOf('.');
    if (comma >= 0 && dot >= 0) {
      const decimal = comma > dot ? ',' : '.';
      s = s.replace(new RegExp('[^0-9+\\-' + (decimal === '.' ? '\\.' : ',') + ']', 'g'), '');
      s = s.replace(decimal, '.');
    } else if (comma >= 0) {
      if (/^[+-]?\d+,[0-9]{3,}$/.test(s)) return NaN; // precise rate, not an amount
      s = /,\d{1,2}$/.test(s) ? s.replace(',', '.') : s.replace(/,/g, '');
    } else if (dot >= 0) {
      if (/^[+-]?\d+\.[0-9]{3,}$/.test(s)) return NaN; // preserve rate precision
      s = /\.\d{1,2}$/.test(s) ? s : s.replace(/\./g, '');
    }
    return Number(s);
  }

  function preservePreciseRate(full, amount) {
    return /^[+-]?\d+[.,]\d{3,}$/.test(amount.trim())
      ? full.replace(amount, amount.replace('.', ','))
      : full;
  }

  function normalizeMoneyText(text) {
    let result = text.replace(/\$\s*([+-]?\d[\d\s\u00a0\u202f.,]*?)\s+USDT\b/gi, (full, amount) => {
      const n = parseDisplayNumber(amount.trim());
      return Number.isFinite(n) ? formatDisplayMoney(n, 'USDT') : preservePreciseRate(full, amount);
    });
    result = result.replace(/\$\s*([+-]?\d[\d\s\u00a0\u202f.,]*)/g, (full, amount) => {
      const n = parseDisplayNumber(amount.trim());
      return Number.isFinite(n) ? formatDisplayMoney(n, '$') + amount.match(/\s*$/)[0] : preservePreciseRate(full, amount);
    });
    result = result.replace(/฿\s*([+-]?\d[\d\s\u00a0\u202f.,]*)/g, (full, amount) => {
      const n = parseDisplayNumber(amount.trim());
      return Number.isFinite(n) ? formatDisplayMoney(n, '฿') + amount.match(/\s*$/)[0] : preservePreciseRate(full, amount);
    });
    result = result.replace(/([+-]?\d[\d\s\u00a0\u202f.,]*?)\s*(₽|฿|USDT|RUB|THB|USD)(?![\w])/gi, (full, amount, cur) => {
      const n = parseDisplayNumber(amount.trim());
      return Number.isFinite(n) ? formatDisplayMoney(n, cur.toUpperCase()) : preservePreciseRate(full, amount);
    });
    return result;
  }

  const EMOJI = /\p{Extended_Pictographic}(?:\uFE0F|\u200D\p{Extended_Pictographic})*/gu;
  function actionLabel(el) {
    const handler = el.getAttribute('onclick') || '';
    if (/delete|remove|del\(/i.test(handler)) return 'Удалить';
    if (/refresh|reload|load/i.test(handler)) return 'Обновить';
    if (/add|create/i.test(handler)) return 'Добавить';
    return el.getAttribute('aria-label') || el.title || 'Открыть';
  }
  function normalizeText(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const parent = node.parentElement;
      if (!parent || parent.closest('script,style,textarea,pre,code,[contenteditable="true"]')) continue;
      let updated = normalizeMoneyText(node.nodeValue);
      const label = node.previousSibling?.nodeType === Node.ELEMENT_NODE ? node.previousSibling.textContent : '';
      if (/\bUSDT\b/i.test(label) && /сумма|объ[её]м|приход|выплата|остаток|себестоимость|прибыль|комиссия/i.test(label)) {
        updated = updated.replace(/\$\s*(\d[\d\s\u00a0\u202f.,]*)/, (full, amount) => {
          const value = parseDisplayNumber(amount.trim());
          return Number.isFinite(value) ? formatDisplayMoney(value, 'USDT') : full;
        });
      }
      const interactive = parent.closest('button,a,[role="tab"],h1,h2,h3,h4,.pill,.badge,.rx-pill');
      if (interactive) updated = updated.replace(EMOJI, symbol => symbol === '↔' ? symbol : '').replace(/\s{2,}/g, ' ');
      if (updated !== node.nodeValue) node.nodeValue = updated;
      if (interactive && (interactive.tagName === 'BUTTON' || interactive.tagName === 'A') && !interactive.textContent.trim()) {
        node.nodeValue = actionLabel(interactive);
      }
    }
  }
  const NUMERIC_HEADER = /сумма|объём|объем|маржа|прибыль|баланс|получили|отправлено|выплачено|\b(?:usd|usdt|rub|thb)\b|[₽฿$]/i;
  const NUMERIC_CELL = /^\s*[+−-]?\s*(?:[$฿]\s*)?\d[\d\s\u00a0\u202f.,]*(?:\s*(?:₽|฿|USDT))?\s*$/i;
  function alignNumbers(root) {
    const tables = root.matches?.('table') ? [root] : root.querySelectorAll?.('table') || [];
    for (const table of tables) {
      table.querySelectorAll('th').forEach(th => { if (NUMERIC_HEADER.test(th.textContent)) th.classList.add('number-cell'); });
      table.querySelectorAll('td').forEach(td => {
        if (!td.querySelector('button,input,select,textarea') && NUMERIC_CELL.test(td.textContent)) td.classList.add('number-cell');
      });
      const headers = table.querySelectorAll('thead tr:last-child th');
      if (!headers.length || [...headers].some(th => Number(th.colSpan) !== 1)) continue;
      const currencies = [...headers].map(th => {
        const label = th.textContent;
        if (/\bUSDT\b/i.test(label)) return 'USDT';
        if (/₽|\bRUB\b/i.test(label)) return '₽';
        if (/฿|\bTHB\b/i.test(label)) return '฿';
        if (/\$|\bUSD\b/i.test(label)) return '$';
        return null;
      });
      table.querySelectorAll('tbody tr').forEach(row => {
        const cells = row.querySelectorAll(':scope > td');
        if (cells.length !== currencies.length) return;
        cells.forEach((cell, index) => {
          const currency = currencies[index];
          const shown = cell.textContent.trim();
          if (!currency || !NUMERIC_CELL.test(shown) || cell.querySelector('button,input,select,textarea')) return;
          const bare = shown.replace(/^[$฿]\s*/, '').replace(/\s*(?:₽|฿|USDT)$/i, '');
          const value = parseDisplayNumber(bare);
          if (!Number.isFinite(value)) return;
          const formatted = formatDisplayMoney(value, currency);
          if (shown === formatted) return;
          if (!cell.children.length) cell.textContent = formatted;
          else if (cell.children.length === 1 && cell.firstElementChild.textContent.trim() === shown) {
            cell.firstElementChild.textContent = formatted;
          }
        });
      });
    }
  }
  function normalizeEmptyStats() {
    const grid = document.getElementById('statsGrid');
    if (!grid) return;
    const first = grid.querySelector('.stat-card .stat-value');
    const empty = first && (first.textContent.trim() === '0' || first.dataset.wave4aEmpty === '1');
    const note = document.getElementById('wave4aDashboardEmpty');
    if (!empty) { if (note) note.remove(); return; }
    for (const value of grid.querySelectorAll('.stat-value')) {
      if (/^(?:[$฿]\s*)?0(?:[.,]00)?(?:\s*(?:₽|฿|USDT))?$/.test(value.textContent.trim())) {
        value.textContent = '—';
        value.dataset.wave4aEmpty = '1';
      }
    }
    if (!note) grid.insertAdjacentHTML('beforebegin', '<p id="wave4aDashboardEmpty" class="empty-state">Сделок за выбранный период нет. Выберите другой период или <button class="btn-link" onclick="showSection(\'create\')">создайте сделку</button>.</p>');
  }
  function process(root) { normalizeText(root); alignNumbers(root); normalizeEmptyStats(); }
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; process(document.body); });
  });
  function start() {
    process(document.body);
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
}());
