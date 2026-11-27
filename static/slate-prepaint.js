/* Inlined before styles on the authenticated working HTML responses. */
(function () {
  const root = document.documentElement;
  let preferences;
  try {
    preferences = JSON.parse(localStorage.getItem('calccrm:slate-preferences'));
  } catch (_) {}
  root.dataset.mode = preferences?.mode === 'light' ? 'light' : 'dark';
  root.dataset.preset = preferences?.preset === 'tangerine' ? 'tangerine' : 'slate';
  root.classList.add('slate-console', 'slate-pending');

  function settle(mounted) {
    if (!root.classList.contains('slate-pending')) return;
    clearTimeout(timeout);
    if (mounted) root.classList.remove('slate-pending', 'slate-failed');
    else root.classList.add('slate-failed');
  }

  const timeout = setTimeout(() => settle(false), 6000);
  window.settleSlatePrepaint = settle;
})();
