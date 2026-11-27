/* Application adapter for the sidebar, inset header and command palette from the Slate template. */
(function () {
  const icons = {
    brand: '<path d="M12 21c-4 0-7-2.8-7-6.6 0-3.8 3.4-6.7 6.8-9.4a.4.4 0 0 1 .5 0c3.3 2.7 6.7 5.6 6.7 9.4 0 3.8-3 6.6-7 6.6Z"/><path d="M12 5c0-1.5 1.6-3 3.5-3"/>',
    panel: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9m-8 12a2 2 0 0 0 4 0"/>',
    down: '<path d="m8 9 4-4 4 4m-8 6 4 4 4-4"/>',
    next: '<path d="m9 6 6 6-6 6"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    theme: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18Z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9A9 9 0 1 1 12 3Z"/>',
    overview: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    analytics: '<path d="M3 3v16a2 2 0 0 0 2 2h16M8 17v-3m5 3v-5m5 5V9"/>',
    balance: '<path d="M20 8V6a2 2 0 0 0-2-2H6a3 3 0 0 0 0 6h14a1 1 0 0 1 1 1v7a2 2 0 0 1-2 2H6a3 3 0 0 1-3-3V7m18 6h-4a2 2 0 0 0 0 4h4"/>',
    tasks: '<path d="m3 6 2 2 3-4m-5 8 2 2 3-4m-5 8 2 2 3-4m3-10h10m-10 6h10m-10 6h10"/>',
    deals: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    documents: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6M8 13h8m-8 4h8"/>',
    referrers: '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v2m2-14a3 3 0 0 1 0 6m1 2a4 4 0 0 1 3 4v2"/>',
    calc: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8m-8 4h.01m4 0h.01m4 0h.01M8 15h.01m4 0h.01m4 0h.01"/>',
    payoutRequests: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18m-14 5h3"/>'
  };
  const icon = name => `<svg class="slate-icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name]}</svg>`;
  const esc = value => String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const root = document.documentElement;
  const phone = matchMedia('(max-width: 767px)');
  const tablet = matchMedia('(max-width: 1023px)');
  const prefKey = 'calccrm:slate-preferences';
  let shell;
  let preferences;

  function readPreferences() {
    try {
      const saved = JSON.parse(localStorage.getItem(prefKey));
      return saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {};
    } catch (_) { return {}; }
  }

  function paintPreferences() {
    const mode = preferences.mode === 'light' ? 'light' : 'dark';
    const preset = preferences.preset === 'tangerine' ? 'tangerine' : 'slate';
    root.dataset.mode = mode;
    root.dataset.preset = preset;
    root.dataset.sidebar = ['rail','open'].includes(preferences.sidebar) ? preferences.sidebar : (tablet.matches ? 'rail' : 'open');
    const toggle = shell.header.querySelector('[data-slate-mode]');
    toggle.innerHTML = icon(mode === 'dark' ? 'sun' : 'moon');
    toggle.setAttribute('aria-label', mode === 'dark' ? 'Светлый режим' : 'Тёмный режим');
    shell.header.querySelectorAll('[data-slate-preset]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.slatePreset === preset));
    });
    shell.trigger.setAttribute('aria-expanded', String(phone.matches ? shell.drawer.open : root.dataset.sidebar !== 'rail'));
  }

  function changePreferences(change) {
    Object.assign(preferences, change);
    try { localStorage.setItem(prefKey, JSON.stringify(preferences)); } catch (_) {}
    paintPreferences();
  }

  function sectionEntry(key) {
    return shell.entries.find(entry => entry.key === key);
  }

  function renderPalette() {
    const query = shell.input.value.toLocaleLowerCase('ru').trim().replace(/ё/g, 'е');
    const matches = shell.entries.filter(({title}) => title.toLocaleLowerCase('ru').replace(/ё/g, 'е').includes(query));
    shell.results.innerHTML = matches.length ? matches.map(({key,title,href,group}) =>
      `<a href="${href}" data-slate-route="${key}"><span>${title}</span><small>${group}</small></a>`).join('') : '<p>Ничего не найдено</p>';
    shell.status.textContent = matches.length ? `Найдено разделов: ${matches.length}` : 'Ничего не найдено';
  }

  function openPalette() {
    if (shell.palette.open || shell.drawer.open) return;
    shell.returnFocus = document.activeElement;
    shell.input.value = '';
    renderPalette();
    shell.palette.showModal();
    shell.input.focus();
  }

  function closeBackdrop(dialog) {
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right ||
          event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
  }

  function handleRoute(event) {
    const link = event.target.closest('a[data-slate-route]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey ||
        event.metaKey || event.altKey || event.shiftKey) return;
    if (shell.palette.open) shell.palette.close();
    if (shell.drawer.open) shell.drawer.close();
    const url = new URL(link.href);
    const section = url.searchParams.get('section');
    if (shell.state.page !== 'crm' || url.pathname !== '/crm' ||
        location.pathname !== '/crm' || url.hash || typeof showSection !== 'function') return;
    event.preventDefault();
    showSection(section || 'deals');
    history.replaceState(null, '', url);
    window.scrollTo(0, 0);
  }

  function mount(state, sections, options) {
    if (window.settleSlatePrepaint && !['slate-shell.css', 'slate-surfaces.css'].every(file =>
      document.querySelector('link[href^="/static/' + file + '"]')?.sheet)) return;
    const {panelAvailable, roleLabel} = options;
    const headings = ['Обзор', 'Работа'];
    const panelLink = panelAvailable ? '/panel' : '/crm?section=dashboard';
    const groups = [
      [
        ['dashboard', 'Дашборд', panelLink, 'overview'],
        ['analytics', 'Аналитика', '/tasks?section=analytics'],
        ['balance', 'Баланс', '/crm?section=balance']
      ],
      [
        ['tasks', 'Задачник', '/tasks'],
        ['deals', 'Сделки', '/crm?section=deals'],
        ['documents', 'Документы', '/crm?section=documents'],
        ...(state.role === 'manager' && !state.stand ? [['referrers', 'Рефереры', '/crm?section=referrers']] : []),
        ['payoutRequests', 'Заявки на выплату', '/crm?section=payoutRequests'],
        ['calc', 'Калькулятор', '/']
      ]
    ];
    const entries = groups.flatMap((items,index) => items.map(([key,title,href]) => ({key,title,href,group:headings[index]})));
    for (const [key,title,href] of sections) {
      if (!entries.some(entry => entry.key === key)) entries.push({key,title,href,group:'CRM'});
    }
    entries.push({key:'instructions',title:'Инструкция',href:'/docs/instruction.html',group:'Справка'});
    entries.push({key:'notifications',title:'Уведомления',href:'/tasks?notifications=1',group:'Задачник'});
    if (['admin','operator'].includes(state.role)) {
      entries.push({key:'operatorGuide',title:'Инструкции для операциониста',href:'/tasks/instructions/',group:'Справка'});
    }
    if (state.role === 'admin') entries.push({key:'history',title:'Архив задач',href:'/tasks?section=history',group:'Задачник'});

    const name = esc(state.name || 'Пользователь');
    const avatar = esc((state.name || '?').trim().charAt(0).toLocaleUpperCase('ru') || '?');
    const app = document.createElement('div');
    app.className = 'slate-app';
    app.innerHTML = `
      <aside class="slate-side" id="slate-sidebar" aria-label="Боковая панель">
        <div class="slate-drawer-head">
          <a class="slate-workspace" href="${panelLink}" aria-label="CalcCRM · Дашборд" title="CalcCRM">
            <span class="slate-brand-mark">${icon('brand')}</span>
            <span class="slate-identity"><strong>CalcCRM</strong><small>Grusha</small></span>
          </a>
          <button type="button" class="slate-icon-button slate-drawer-close" aria-label="Закрыть навигацию">${icon('close')}</button>
        </div>
        <nav class="slate-side-nav" aria-label="Разделы">
          ${groups.map((items,index) => `<div class="slate-group" role="group" aria-labelledby="slate-group-${index}">
            <span class="slate-group-label" id="slate-group-${index}">${headings[index]}</span>
            <div class="slate-group-links">${items.map(([key,title,href,mark]) => `<a class="slate-link" href="${href}" data-slate-route="${key}" data-shell-link="${key}" title="${title}">
              ${icon(mark || key)}<span class="slate-link-label">${title}</span>${key==='tasks'?'<span class="slate-count site-shell-count" hidden></span>':''}</a>`).join('')}</div>
          </div>`).join('')}
        </nav>
        <div class="slate-side-footer">
          <details class="slate-details slate-user">
            <summary aria-label="Профиль: ${name} · ${esc(roleLabel)}" title="${name}">
              <span class="slate-avatar" aria-hidden="true">${avatar}</span>
              <span class="slate-identity"><strong>${name}</strong><small>${esc(roleLabel)}</small></span>${icon('down')}
            </summary>
            <div class="slate-menu">
              ${state.rolePreview ? '<span class="slate-menu-label">Смотреть как…</span><div data-shell-roles></div>' : ''}
              ${entries.filter(entry=>['operatorGuide','instructions','history'].includes(entry.key)).map(({title,href})=>`<a href="${href}">${title}</a>`).join('')}
              <button type="button" data-shell-logout>Выйти</button>
            </div>
          </details>
        </div>
      </aside>
      <div class="slate-inset">
        <header class="slate-topbar">
          <button type="button" class="slate-icon-button" data-slate-sidebar aria-label="Переключить навигацию" aria-controls="slate-sidebar" aria-expanded="true"><span class="slate-only-desktop">${icon('panel')}</span><span class="slate-only-mobile">${icon('menu')}</span></button>
          <nav class="slate-crumbs" aria-label="Текущий раздел">
            <span class="slate-crumb-parent"></span>${icon('next')}<span aria-current="page"></span>
          </nav>
          <div class="slate-top-actions">
            <button type="button" class="slate-search" data-slate-search aria-label="Найти раздел" aria-keyshortcuts="Control+K Meta+K" aria-haspopup="dialog">
              ${icon('search')}<span>Найти раздел</span><kbd class="slate-key">${/Mac/i.test(navigator.platform) ? 'Cmd' : 'Ctrl'} K</kbd>
            </button>
            <div class="slate-notifications"><a class="slate-icon-button" href="/tasks?notifications=1" aria-label="Уведомления">${icon('bell')}<span class="slate-alert-count" hidden></span></a></div>
            <details class="slate-details slate-theme">
              <summary class="slate-icon-button" aria-label="Цветовая схема" title="Цветовая схема">${icon('theme')}</summary>
              <div class="slate-menu" aria-label="Цветовая схема">
                <button type="button" data-slate-preset="slate">Slate</button>
                <button type="button" data-slate-preset="tangerine">Tangerine</button>
              </div>
            </details>
            <button type="button" class="slate-icon-button" data-slate-mode></button>
          </div>
        </header>
        <div id="slate-content" tabindex="-1"></div>
      </div>
      <dialog class="slate-dialog slate-drawer" aria-label="Навигация"></dialog>
      <dialog class="slate-dialog slate-palette" aria-label="Найти раздел">
        <div class="slate-searchbar">${icon('search')}<input type="search" aria-label="Название раздела" placeholder="Найти раздел…" autocomplete="off" autofocus>
          <button type="button" class="slate-icon-button" aria-label="Закрыть поиск">${icon('close')}</button>
        </div>
        <p class="slate-sr-only" role="status"></p>
        <nav class="slate-results" aria-label="Результаты поиска"></nav>
      </dialog>`;

    const sidebar = app.querySelector('.slate-side');
    const header = app.querySelector('.slate-topbar');
    const trigger = header.querySelector('[data-slate-sidebar]');
    const drawer = app.querySelector('.slate-drawer');
    const palette = app.querySelector('.slate-palette');
    const content = app.querySelector('#slate-content');
    shell = {state, entries, header, trigger, drawer, palette, input:palette.querySelector('input'),
      status:palette.querySelector('[role="status"]'), results:palette.querySelector('.slate-results')};
    preferences = readPreferences();

    const payout = document.getElementById('payoutRequestsBadge');
    if (payout) app.querySelector('[data-slate-route="payoutRequests"]').append(payout);
    const roles = document.getElementById('roles');
    if (roles && state.rolePreview) app.querySelector('[data-shell-roles]').append(roles);
    const bell = document.getElementById('bell');
    if (bell && state.page === 'tasks') header.querySelector('.slate-notifications').replaceChildren(bell);

    const skip = document.createElement('a');
    skip.className = 'slate-skip';
    skip.href = '#slate-content';
    skip.textContent = 'К содержимому';
    skip.addEventListener('click', event => {
      event.preventDefault();
      content.focus();
      content.scrollIntoView({block:'start'});
    });
    const contentNodes = [...document.body.childNodes].filter(node => node.nodeName !== 'SCRIPT');
    content.append(...contentNodes);
    document.body.prepend(skip,app);
    root.classList.add('slate-console');
    paintPreferences();

    trigger.addEventListener('click', () => {
      if (!phone.matches) {
        changePreferences({sidebar:root.dataset.sidebar === 'rail' ? 'open' : 'rail'});
        return;
      }
      drawer.append(sidebar);
      drawer.showModal();
      trigger.setAttribute('aria-expanded','true');
      sidebar.querySelector('.slate-drawer-close').focus();
    });
    drawer.addEventListener('close', () => {
      sidebar.querySelector('.slate-user').open = false;
      app.prepend(sidebar);
      paintPreferences();
      trigger.focus();
    });
    sidebar.querySelector('.slate-drawer-close').addEventListener('click', () => drawer.close());
    phone.addEventListener('change', () => { if (drawer.open) drawer.close(); else paintPreferences(); });
    tablet.addEventListener('change', paintPreferences);

    const themeMenu = header.querySelector('.slate-theme');
    const profileMenu = sidebar.querySelector('.slate-user');
    app.addEventListener('click', handleRoute);
    document.addEventListener('click', event => {
      for (const details of [themeMenu, profileMenu]) {
        if (details.open && !details.contains(event.target)) details.open = false;
      }
    });
    profileMenu.addEventListener('click', event => {
      if (event.target.closest('.rolebtn')) {
        profileMenu.open = false;
        if (drawer.open) drawer.close();
        else profileMenu.querySelector('summary').focus();
      }
    });
    themeMenu.addEventListener('click', event => {
      const preset = event.target.closest('[data-slate-preset]')?.dataset.slatePreset;
      if (!preset) return;
      changePreferences({preset});
      themeMenu.open = false;
      themeMenu.querySelector('summary').focus();
    });
    header.querySelector('[data-slate-mode]').addEventListener('click', () => {
      changePreferences({mode:root.dataset.mode === 'dark' ? 'light' : 'dark'});
    });
    sidebar.querySelector('[data-shell-logout]').addEventListener('click', async () => {
      await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});
      location.href = '/login';
    });
    header.querySelector('[data-slate-search]').addEventListener('click', openPalette);
    palette.querySelector('button').addEventListener('click', () => palette.close());
    palette.addEventListener('close', () => shell.returnFocus?.focus());
    closeBackdrop(palette);
    closeBackdrop(drawer);
    shell.input.addEventListener('input', renderPalette);
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !event.isComposing) {
        event.preventDefault();
        if (palette.open) palette.close(); else openPalette();
      }
      if (event.key === 'Escape' && !palette.open) {
        const openMenu = [themeMenu,profileMenu].find(menu => menu.open);
        if (openMenu) {
          event.preventDefault();
          openMenu.open = false;
          openMenu.querySelector('summary').focus();
        }
      }
    });
    palette.addEventListener('keydown', event => {
      if (event.isComposing || event.keyCode === 229) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        palette.close();
        return;
      }
      const results = [...shell.results.querySelectorAll('a')];
      if (!results.length) return;
      const current = results.indexOf(document.activeElement);
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const next = event.key === 'ArrowDown' ? results[current + 1] :
          current < 0 ? results.at(-1) : results[current - 1];
        (next || shell.input).focus();
      } else if (event.key === 'Enter' && document.activeElement === shell.input) {
        event.preventDefault();
        results[0].click();
      }
    });
    update(state);
    window.settleSlatePrepaint?.(true);
  }

  function update(state) {
    if (!shell) return;
    shell.state = state;
    const key = state.section || (state.page === 'crm' ? state.active === 'panel' ? 'dashboard' : 'deals' :
      new URLSearchParams(location.search).get('section') || state.page);
    const entry = sectionEntry(key);
    const title = shell.header.querySelector('[aria-current="page"]');
    title.textContent = entry?.title || 'CRM';
    shell.header.querySelector('.slate-crumb-parent').textContent = entry?.group || 'Работа';
    document.querySelectorAll('.slate-link[data-slate-route]').forEach(link => {
      if (link.dataset.slateRoute === key) link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
    });
    const count = document.querySelector('.slate-link .slate-count');
    count.hidden = !state.count;
    count.textContent = state.count || '';
    const alerts = shell.header.querySelector('.slate-alert-count');
    if (alerts) {
      alerts.hidden = !state.notifications;
      alerts.textContent = state.notifications || '';
      alerts.parentElement.setAttribute('aria-label', state.notifications ? `Уведомления: ${state.notifications} новых` : 'Уведомления');
    }
  }

  window.SlateShell = {mount,update};
})();
