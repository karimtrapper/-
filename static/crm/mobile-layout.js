/* Presentation only: compact CRM lists and filters below the tablet breakpoint.
   The original cells, handlers, and row data stay in the table for desktop. */
(function () {
  'use strict';

  const columns = {
    deals: { title: 3, amount: 6, status: 9 },
    incomes: { title: 2, amount: 3, status: 5 },
    conversions: { title: 3, amount: 7, status: 9 },
    balance: { title: 3, amount: 2 },
    exchangers: { title: 2, amount: 4, status: 8 }
  };
  const exchangerColumns = {
    'rx-deals-body': { title: 2, amount: 4, status: 8 },
    'rx-brokers-body': { title: 2, amount: 5, status: 7 },
    'rx-requests-body': { title: 1, amount: 2, status: 7 },
    'rx-wallets-body': { title: 0, amount: 3, status: 5 }
  };
  const titlePattern = /клиент|плательщик|мерчант|брокер|реферер|партнёр|адрес|описание|название|имя|кошелёк/i;
  const amountPattern = /сумма|usdt|thb|баланс|прибыль|объём|отправлено|получили|маржа|₽|\$/i;
  const statusPattern = /статус|состояние|вид/i;

  function enhanceTable(table) {
    if (!table.closest('section.section')) return;
    const section = table.closest('section.section').id;
    const headers = [...table.querySelectorAll('thead tr:last-child th')].map(th => th.textContent.trim());
    const config = exchangerColumns[table.tBodies[0]?.id] || columns[section] || {};
    const rows = [...table.querySelectorAll('tbody > tr')];
    table.classList.add('crm-mobile-table');
    if (!rows.length) return;
    if (table.classList.contains('unit-econ-table')) {
      enhanceUnitEconTable(table, rows, headers);
      return;
    }
    rows.forEach(row => {
      if (row.dataset.crmCardReady === '1') return;
      const cells = [...row.children].filter(cell => cell.tagName === 'TD');
      if (!cells.length) return;
      row.dataset.crmCardReady = '1';
      if (cells.length === 1 && cells[0].colSpan > 1) {
        row.classList.add('crm-mobile-empty-row');
        return;
      }
      const meaningful = index => cells[index] && cells[index].textContent.trim() && !cells[index].querySelector('input[type="checkbox"]');
      const title = meaningful(config.title) ? config.title
        : headers.findIndex((label, index) => titlePattern.test(label) && meaningful(index));
      const titleIndex = title >= 0 ? title : Math.max(0, cells.findIndex(cell => cell.textContent.trim()));
      const amount = config.amount < cells.length ? config.amount
        : headers.findIndex((label, index) => index !== titleIndex && amountPattern.test(label) && meaningful(index));
      const status = config.status < cells.length ? config.status
        : headers.findIndex((label, index) => index !== titleIndex && index !== amount && statusPattern.test(label) && meaningful(index));
      const action = cells.findIndex(cell => [...cell.querySelectorAll('button, a')].some(control =>
        /^Детали$/i.test(control.textContent.trim())));

      cells.forEach((cell, index) => {
        cell.dataset.crmLabel = headers[index] || `Поле ${index + 1}`;
        cell.dataset.crmCardRole = cell.querySelector('input[type="checkbox"]') ? 'selection'
          : index === titleIndex ? 'title'
          : index === amount ? 'amount' : index === status ? 'status'
          : index === action ? 'action' : 'extra';
      });
      if (action >= 0) return;
      addDetailsButton(row, cells[titleIndex], section);
    });
  }

  /* Дашборд (.unit-econ-table — «Маржа», «Юнит-экономика», «По каналам»):
     вертикальный список «метка — значение» вместо широкой таблицы сравнения
     и кнопки «Детали» — переход по тапу на всю строку, как .crm-deal-row
     (находка №15 по аналогии; редизайн дашборда ui-2026-10-17, 375px). */
  function headerName(th) {
    if (!th) return '';
    const clone = th.cloneNode(true);
    clone.querySelectorAll('.ue-sub').forEach(sub => sub.remove());
    return clone.textContent.trim();
  }

  function enhanceUnitEconTable(table, rows, headers) {
    const headerCells = [...table.querySelectorAll('thead tr:last-child th')];
    const subs = headerCells.map(th => {
      const sub = th.querySelector('.ue-sub');
      return sub ? sub.textContent.trim() : '';
    });
    rows.forEach(row => {
      if (row.dataset.crmCardReady === '1') return;
      const cells = [...row.children].filter(cell => cell.tagName === 'TD');
      if (!cells.length) return;
      row.dataset.crmCardReady = '1';
      if (cells.length === 1 && cells[0].colSpan > 1) {
        row.classList.add('crm-mobile-empty-row');
        return;
      }
      const metricTitle = row.querySelector(':scope > th');
      if (metricTitle) {
        // marginsTable: th — название метрики, td×N — значения по периодам.
        // Первый период виден всегда, остальные — вертикальным списком по тапу.
        metricTitle.dataset.crmCardRole = 'title';
        cells.forEach((cell, index) => {
          cell.dataset.crmLabel = headerName(headerCells[index + 1]) || `Показатель ${index + 1}`;
          cell.dataset.crmCardRole = index === 0 ? 'amount' : 'extra';
        });
        if (cells.length > 1) makeRowExpandable(row);
        return;
      }
      if (table.id === 'channelsTable') {
        // channelsTable: первая ячейка — название канала, остальные — метрики.
        cells[0].dataset.crmCardRole = 'title';
        cells.forEach((cell, index) => {
          if (index === 0) return;
          cell.dataset.crmLabel = headerName(headerCells[index]) || `Поле ${index + 1}`;
          cell.dataset.crmCardRole = 'extra';
        });
        makeRowExpandable(row);
        return;
      }
      // unitEconTable: один <tr> с N метриками → плоский вертикальный список
      // «метка — значение», пояснение метрики — мелким текстом под меткой.
      cells.forEach((cell, index) => {
        cell.dataset.crmCardRole = 'metric';
        cell.dataset.crmLabel = headerName(headerCells[index]) || `Показатель ${index + 1}`;
        cell.dataset.crmSub = subs[index] || '';
      });
    });
  }

  function makeRowExpandable(row) {
    row.classList.add('crm-mobile-expandable');
    row.tabIndex = 0;
    row.setAttribute('role', 'button');
    row.setAttribute('aria-expanded', 'false');
    const toggle = () => {
      const open = row.classList.toggle('crm-mobile-expanded');
      row.setAttribute('aria-expanded', String(open));
    };
    row.addEventListener('click', event => {
      if (event.target.closest('a, button, input, label')) return;
      toggle();
    });
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); }
    });
  }

  function addDetailsButton(row, titleCell, section) {
      const chevron = section === 'incomes';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = chevron ? 'crm-mobile-details crm-mobile-chevron' : 'crm-mobile-details';
      button.textContent = chevron ? '⌄' : 'Детали';
      button.setAttribute('aria-label', 'Детали');
      button.setAttribute('aria-expanded', 'false');
      const toggle = () => {
        const open = row.classList.toggle('crm-mobile-expanded');
        button.setAttribute('aria-expanded', String(open));
        if (chevron) button.setAttribute('aria-label', open ? 'Свернуть' : 'Детали');
        else button.textContent = open ? 'Свернуть' : 'Детали';
      };
      button.addEventListener('click', event => { event.stopPropagation(); toggle(); });
      if (chevron) {
        row.addEventListener('click', event => {
          if (event.target.closest('input, a, button, label')) return;
          toggle();
        });
      }
      titleCell.append(button);
  }

  function addFilterToggle(selector) {
    const panel = document.querySelector(selector);
    if (!panel || panel.dataset.crmFilterReady === '1') return;
    panel.dataset.crmFilterReady = '1';
    panel.classList.add('crm-mobile-filter-panel');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'crm-mobile-filter-toggle';
    button.textContent = 'Фильтры';
    button.setAttribute('aria-expanded', 'false');
    button.addEventListener('click', () => {
      const open = panel.classList.toggle('is-open');
      button.setAttribute('aria-expanded', String(open));
      button.textContent = open ? 'Скрыть фильтры' : 'Фильтры';
    });
    panel.before(button);
  }

  function markPrimary() {
    const section = document.querySelector('section.section.active');
    const first = section && [...section.querySelectorAll('.btn-primary')].find(button =>
      !button.disabled && button.getClientRects().length &&
      (section.id !== 'verification' || button.closest('.card') === section.querySelector('.card')) &&
      !button.closest('.modal, .modal-overlay, [role="dialog"]'));
    document.querySelectorAll('section.section .crm-mobile-primary').forEach(button => {
      if (button !== first) button.classList.remove('crm-mobile-primary');
    });
    if (first && !first.classList.contains('crm-mobile-primary')) first.classList.add('crm-mobile-primary');
  }

  let queued = false;
  function refresh() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      document.querySelectorAll('section.section table').forEach(enhanceTable);
      markPrimary();
    });
  }

  function init() {
    [
      '#deals > .crm-section-head + .card',
      '#periodSelector',
      '#rx-postup > .card > div:first-child',
      '#transactions #walletFilter',
      '#payoutRequests .card-title > div',
      '#referrers #refSearch',
      '#documents #docsSearch',
      '#incomes #incomesShowExcluded',
      '#verification > .card:first-of-type > .form-row'
    ].forEach(selector => {
      const element = document.querySelector(selector);
      if (!element) return;
      if (selector.includes('#walletFilter')) addFilterToggleTarget(element.closest('.form-row'));
      else if (selector.includes('#refSearch')) addFilterToggleTarget(element.parentElement);
      else if (selector.includes('#incomesShowExcluded')) addFilterToggleTarget(element.closest('label'));
      else addFilterToggleTarget(element);
    });
    const root = document.querySelector('.container');
    if (root) new MutationObserver(refresh).observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style', 'disabled'] });
    refresh();
  }

  function addFilterToggleTarget(element) {
    if (!element) return;
    if (!element.id) element.id = `crmMobileFilter${document.querySelectorAll('.crm-mobile-filter-panel').length + 1}`;
    addFilterToggle(`#${element.id}`);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
