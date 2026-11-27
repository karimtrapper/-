(function () {
  'use strict';

  const page = '/tasks?section=history';
  const api = '/api/stand/task-history';
  const parseId = value => /^[1-9]\d*$/.test(String(value)) ? String(value) : null;

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function link(text, href, className) {
    const node = element('a', text, className);
    node.href = href;
    return node;
  }

  function cardLink(card, view) {
    const id = parseId(card.id);
    if (!id) return null;
    const kind = card.source_kind === 'legacy_deal' ? 'legacy_deal' : 'task_history';
    return link([card.code, card.client].filter(Boolean).join(' · '), `${page}&view=${view}&${kind}=${id}`);
  }

  function showFileLinks(documents) {
    const list = element('ul');
    for (const file of documents || []) {
      if (!/^\/api\/stand\/task-history\/(?:(?:board|legacy_deal|agreements)\/\d+\/documents\/\d+|unattached-files\/[0-9a-f]{32})$/.test(file.url)) continue;
      const item = element('li');
      item.append(link(file.name || 'Документ', `${file.url}?download=1`));
      if (file.deleted) item.append(' (удалён в исходной карточке)');
      list.append(item);
    }
    return list.childElementCount ? list : null;
  }

  function addFileList(parent, files) {
    const list = showFileLinks(files);
    if (list) parent.append(element('h2', 'Документы'), list);
  }

  function showDecisionEvidence(parent, title, decision) {
    if (!decision) return;
    const facts = [...(decision.evidence || []), ...(decision.details || [])];
    if (!decision.reason && !facts.length) return;
    const section = element('section');
    section.append(element('h3', title));
    if (decision.reason) section.append(element('p', decision.reason));
    if (facts.length) {
      const list = element('ul');
      for (const fact of facts) list.append(element('li', fact));
      section.append(list);
    }
    parent.append(section);
  }

  function showCard(container, card, role) {
    const section = element('section', '', 'card');
    section.append(element('h2', [card.code, card.client].filter(Boolean).join(' · ')));
    const summary = [card.type, card.created_at, card.source_status].filter(Boolean);
    if (summary.length) section.append(element('p', summary.join(' · ')));
    const sourceState = {closed: 'Закрыта на исходной доске', open: 'Закрытие не отмечено', unknown: 'Состояние неизвестно'};
    const decision = {attach: 'Связана со сделкой CRM', archive: 'В архиве', review: 'На сверке', move: 'Перенесена в задачник'};
    section.append(element('p', [sourceState[card.source_state], card.source_outcome, decision[card.decision]]
      .filter(Boolean).join(' · ')));
    const dealId = parseId(card.crm_deal_id);
    if (dealId) section.append(link(`Сделка №${dealId} в CRM`, `/crm?deal=${dealId}`));
    if (card.canonical) {
      const statuses = {COMPLETED: 'Завершена', VERIFIED: 'Проверена', LOSE: 'Отказ', NOT_LEAD: 'Не обращение', PENDING: 'В работе'};
      const result = statuses[card.canonical.status] || 'Статус не указан';
      section.append(element('p', `Итог в CRM — ${result}`));
      const payout = card.canonical.payout;
      if (payout && Number.isFinite(payout.amount)) {
        const amount = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 8}).format(payout.amount);
        section.append(element('p', `Выплата по сделке — ${amount} ${payout.currency}`));
      }
    }
    if (role === 'admin') {
      showDecisionEvidence(section, 'Основание привязки', card.attachment);
      showDecisionEvidence(section, 'Основание для сверки', card.review);
    }
    if (role === 'admin' && card.candidates?.length) {
      const candidates = element('ul');
      for (const value of card.candidates) {
        const id = parseId(value);
        if (!id) continue;
        const item = element('li');
        item.append(link(`Сделка №${id}`, `/crm?deal=${id}`));
        candidates.append(item);
      }
      section.append(element('h3', 'Сделки для сверки'), candidates);
    }
    addFileList(section, card.documents);
    for (const [label, entries] of [['Журнал', card.log], ['Заметки', card.notes]]) {
      if (!entries?.length) continue;
      const list = element('ul');
      for (const entry of entries) {
        list.append(element('li', [entry.ts, entry.author, entry.text].filter(Boolean).join(' · ')));
      }
      section.append(element('h3', label), list);
    }
    container.append(section);
  }

  function showCards(container, cards, view) {
    if (!cards.length) {
      container.append(element('p', 'Карточек пока нет', 'empty'));
      return;
    }
    const list = element('ul', '', 'card');
    for (const card of cards) {
      const anchor = cardLink(card, view);
      if (!anchor) continue;
      const item = element('li');
      item.append(anchor);
      const summary = [card.type, card.source_status].filter(Boolean).join(' · ');
      if (summary) item.append(element('p', summary));
      list.append(item);
    }
    container.append(list);
  }

  function showAgreements(container, agreements, unattachedFiles) {
    if (!agreements.length && !unattachedFiles.length) {
      container.append(element('p', 'Документов пока нет', 'empty'));
      return;
    }
    for (const agreement of agreements) {
      const details = element('details', '', 'card');
      details.append(element('summary', [agreement.number, agreement.client].filter(Boolean).join(' · ')));
      const documents = showFileLinks(agreement.documents);
      if (documents) details.append(documents);
      container.append(details);
    }
    const files = showFileLinks(unattachedFiles);
    if (files) {
      const details = element('details', '', 'card');
      details.append(element('summary', 'Вложения без карточки'), files);
      container.append(details);
    }
  }

  async function mount(container, role) {
    container.classList.add('task-history-view');
    const query = new URLSearchParams(window.location.search);
    const views = {archive: 'Архив', review: 'На сверке', agreements: 'Договоры'};
    const view = Object.hasOwn(views, query.get('view')) ? query.get('view') : 'archive';
    const boardId = parseId(query.get('task_history'));
    const legacyId = parseId(query.get('legacy_deal'));
    const detail = boardId ? `/board/${boardId}` : legacyId ? `/legacy_deal/${legacyId}` : '';
    container.replaceChildren(element('h1', detail ? 'История карточки' : views[view], 'page-h'));
    if (role === 'admin') {
      const navigation = element('nav', '', 'task-toolbar');
      navigation.setAttribute('aria-label', 'История задачника');
      for (const [key, title] of Object.entries(views)) {
        const tab = link(title, `${page}&view=${key}`, `btn btn-sm ${view === key ? 'btn-primary' : 'btn-outline'}`);
        if (!detail && view === key) tab.setAttribute('aria-current', 'page');
        navigation.append(tab, ' ');
      }
      container.append(navigation);
    }
    const status = element('p', 'Загрузка…');
    status.setAttribute('role', 'status');
    container.append(status);
    try {
      const target = detail || (view === 'agreements' ? '/agreements' : `?decision=${view}`);
      const response = await fetch(`${api}${target}`, {credentials: 'same-origin', cache: 'no-store'});
      if (response.status === 401) {
        window.location.href = '/login';
        return;
      }
      if (!response.ok) {
        status.textContent = [403, 404].includes(response.status) ? 'История недоступна' : 'Не удалось загрузить историю';
        return;
      }
      const data = await response.json();
      status.remove();
      if (detail) showCard(container, data.card, role);
      else if (view === 'agreements') showAgreements(container, data.agreements, data.unattached_files);
      else showCards(container, data.cards, view);
    } catch (_) {
      status.textContent = 'Не удалось загрузить историю';
      if (!status.isConnected) container.append(status);
    }
  }

  window.StandTaskHistory = {mount};
})();
