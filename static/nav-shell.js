/* Shared stand navigation. SVG paths and layout follow redesign/mockups/nav.js. */
(function () {
  const ICONS = {
    panel:'<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    calc:'<rect x="5" y="2.5" width="14" height="19" rx="2"/><path d="M8.5 6.5h7M8.5 11h.01M12 11h.01M15.5 11h.01M8.5 14.5h.01M12 14.5h.01M15.5 14.5h.01M8.5 18h.01M12 18h.01M15.5 18h.01"/>',
    tasks:'<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1.5 1.5L7.5 5M3.5 12l1.5 1.5L7.5 11M3.5 18l1.5 1.5 2.5-2.5"/>',
    crm:'<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
    bell:'<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    down:'<path d="m6 9 6 6 6-6"/>'
  };
  const svg = key => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[key]}</svg>`;
  const labels = {admin:'админ',manager:'менеджер',operator:'операционист',findir:'финдир',teodor:'Теодор'};
  const panelRoles = new Set(['admin','findir','teodor']);
  let state = null;
  const esc = value => String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function links(mobile) {
    const items = [
      ['panel','Панель','/panel'],['calc','Калькулятор','/'],
      ['tasks','Задачник','/tasks'],['crm','CRM','/crm']
    ].filter(([key]) => key !== 'panel' || panelRoles.has(state.role));
    return items.map(([key,title,href]) => `<a data-shell-link="${key}" href="${href}" class="${key === state.active ? 'on' : ''}" ${key === state.active ? 'aria-current="page"' : ''}>${svg(key)}<span>${title}</span>${key === 'tasks' ? `<span class="site-shell-count" ${state.count ? '' : 'hidden'}>${state.count || ''}</span>` : ''}</a>`).join('');
  }

  function profile() {
    const name = esc(state.name || 'Пользователь');
    const role = esc(labels[state.role] || state.role);
    const initial = esc((state.name || '?').trim().charAt(0).toUpperCase());
    return `<details class="site-shell-profile"><summary aria-label="Профиль: ${name} · ${role}"><span class="site-shell-avatar">${initial}</span><span class="site-shell-profile-name">${name} · ${role}</span>${svg('down')}</summary><div class="site-shell-menu">${state.page === 'tasks' ? '<div class="site-shell-menu-title">Курсы</div><div data-shell-market></div>' : ''}${state.role === 'admin' && state.page === 'tasks' ? '<div class="site-shell-menu-title">Смотреть как…</div><div data-shell-roles></div><div data-shell-admin-tools></div><div data-shell-build></div>' : ''}<a href="/docs/instruction.html" target="_blank" rel="noopener">Инструкция</a><button type="button" data-shell-logout>Выйти</button></div></details>`;
  }

  function bell() {
    return `<span class="site-shell-bell" data-shell-bell><a href="/tasks?notifications=1" aria-label="Уведомления" style="color:inherit;display:inline-flex;padding:6px">${svg('bell')}</a></span>`;
  }

  function mount(options) {
    if (!options || !options.stand) return;
    state = {...options};
    document.body.classList.add('nav-shell-on','nav-shell-'+state.page);
    document.body.classList.toggle('nav-shell-panel',state.active === 'panel');
    const top = document.createElement('header');
    top.className = 'site-shell site-shell-top';
    top.innerHTML = `<div class="site-shell-brand"><i></i>Grusha</div><nav class="site-shell-links" aria-label="Разделы">${links(false)}</nav><div class="site-shell-right">${bell()}${profile()}</div>`;
    const mobile = document.createElement('div');
    mobile.className = 'site-shell site-shell-mobile-head';
    mobile.innerHTML = `<span>${state.page === 'panel' ? 'Панель' : state.page === 'calc' ? 'Калькулятор' : state.page === 'tasks' ? 'Задачник' : 'CRM'}</span>${bell()}${profile()}`;
    const bottom = document.createElement('nav');
    bottom.className = 'site-shell site-shell-bottom';
    bottom.setAttribute('aria-label','Разделы');
    bottom.style.setProperty('--shell-columns',panelRoles.has(state.role) ? 4 : 3);
    bottom.innerHTML = links(true);
    document.body.prepend(top,mobile);
    document.body.append(bottom);
    if (state.page === 'tasks') {
      const roles = document.getElementById('roles');
      const tools = document.getElementById('admintools');
      const taskBell = document.getElementById('bell');
      const market = document.getElementById('market');
      if (market) top.querySelector('[data-shell-market]').append(market);
      if (state.role === 'admin') {
        top.querySelector('[data-shell-roles]').append(roles);
        top.querySelector('[data-shell-admin-tools]').append(tools);
        const build=document.querySelector('.proto .build');
        if (build) {
          top.querySelector('[data-shell-build]').append(build);
          mobile.querySelector('[data-shell-build]').innerHTML=build.outerHTML;
        }
        // Only one live role switcher is needed; CSS shows this profile on desktop.
      }
      if (taskBell) {
        top.querySelector('[data-shell-bell]').replaceChildren(taskBell);
      }
    }
    document.querySelectorAll('[data-shell-logout]').forEach(button => button.addEventListener('click', async () => {
      await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});
      location.href='/login';
    }));
  }

  function update(changes) {
    if (!state) return;
    Object.assign(state,changes);
    document.body.classList.toggle('nav-shell-panel',state.active === 'panel');
    if (state.page === 'tasks' && state.role === 'admin') {
      const source=document.getElementById('roles');
      const mobile=document.querySelector('.site-shell-mobile-head [data-shell-roles]');
      if (source && mobile) mobile.innerHTML=source.innerHTML;
      const tools=document.getElementById('admintools');
      const mobileTools=document.querySelector('.site-shell-mobile-head [data-shell-admin-tools]');
      if (tools && mobileTools) mobileTools.innerHTML=tools.innerHTML;
    }
    if (state.page === 'tasks') {
      const desktopBell=document.getElementById('bell');
      const mobileBell=document.querySelector('.site-shell-mobile-head [data-shell-bell]');
      if (desktopBell && mobileBell) mobileBell.innerHTML=desktopBell.innerHTML;
      const market=document.getElementById('market');
      const mobileMarket=document.querySelector('.site-shell-mobile-head [data-shell-market]');
      if (market && mobileMarket) mobileMarket.innerHTML=market.innerHTML;
    } else {
      document.querySelectorAll('[data-shell-bell]').forEach(bell => {
        const link=bell.querySelector('a');
        if (!link) return;
        let badge=bell.querySelector('.badge');
        if (state.notifications) {
          if (!badge) {
            badge=document.createElement('b');
            badge.className='badge';
            bell.append(badge);
          }
          badge.textContent=state.notifications;
        } else if (badge) badge.remove();
      });
    }
    document.querySelectorAll('[data-shell-link]').forEach(link => {
      const key=link.dataset.shellLink;
      link.classList.toggle('on',key === state.active);
      if (key === state.active) link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
      if (key === 'tasks') {
        const badge=link.querySelector('.site-shell-count');
        badge.hidden = !state.count;
        badge.textContent = state.count || '';
      }
    });
  }

  async function boot(page) {
    try {
      const response=await fetch('/api/auth/me',{credentials:'same-origin'});
      const data=await response.json();
      if (!data.success || !data.user || data.user.stand !== true) return;
      const role=data.user.role || 'admin';
      const active=page === 'crm' && location.pathname === '/panel' ? 'panel' : page;
      mount({stand:true,page,active,role,name:data.user.display_name || data.user.username,count:0});
      if (page === 'crm') {
        // /panel opens the existing CRM dashboard. /crm is the operational CRM.
        if (typeof showSection === 'function') showSection(active === 'panel' ? 'dashboard' : 'deals');
      }
      try {
        const countResponse=await fetch('/api/stand/nav-count',{credentials:'same-origin'});
        const countData=await countResponse.json();
        if (countData.success) update({count:countData.count,notifications:countData.notifications || 0});
      } catch (error) { /* Navigation remains usable if the count cannot load. */ }
    } catch (error) { /* Keep the existing production navigation on auth failure. */ }
  }
  window.NavShell={mount,update,boot};
})();
