/* Served only in the STAND_MODE CRM response. API guards remain authoritative. */
const standDisabled = 'На стенде отключено';

loadBitrixDeals = async function () {
    const box = document.getElementById('bitrixDealsList');
    box.textContent = 'Проверяю доступность Bitrix…';
    try {
        const response = await fetch(`${API_URL}/api/bitrix/active-deals`);
        const data = await response.json();
        if (response.status === 403 && data.error === 'stand_blocked') {
            box.innerHTML = '<div class="alert alert-info">' + standDisabled +
                ': закрытие сделок в Bitrix недоступно. Сделки CalcCRM доступны в разделе «Сделки».</div>';
            return;
        }
        box.textContent = data.error || 'Не удалось загрузить сделки Bitrix';
    } catch (error) {
        box.textContent = 'Bitrix не отвечает';
    }
};

loadWebhookConfig = async function () {
    const status = document.getElementById('webhookStatus');
    try {
        const response = await fetch(`${API_URL}/api/webhook/config`);
        const data = await response.json();
        if (response.status === 403 && data.error === 'stand_blocked') {
            status.textContent = standDisabled + ': отправка уведомлений через webhook недоступна.';
            return;
        }
        updateWebhookStatus(data.is_configured);
    } catch (error) {
        status.textContent = 'Не удалось проверить webhook';
    }
};

testWebhook = function () {
    document.getElementById('webhookStatus').textContent =
        standDisabled + ': тестовое уведомление через webhook не отправляется.';
};

saveWebhookConfig = function () {
    document.getElementById('webhookStatus').textContent =
        standDisabled + ': настройка webhook здесь недоступна.';
};

// Both desktop tabs and the mobile menu open the verification section.
const standShowSection = showSection;
showSection = function (name) {
    const result = standShowSection.apply(this, arguments);
    if (name === 'verification') loadWebhookConfig();
    return result;
};
document.querySelector('[data-section="verification"]')?.addEventListener('click', loadWebhookConfig);
