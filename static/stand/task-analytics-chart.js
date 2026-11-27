(() => {
  const series = ['Создано', 'Закрыто'];
  const pageSize = 7;
  const count = new Intl.NumberFormat('ru-RU');
  const dateLabel = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'
  });
  const shortDate = new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', timeZone: 'UTC'
  });
  const asDate = day => new Date(day + 'T00:00:00Z');

  class TaskAnalyticsChart extends HTMLElement {
    connectedCallback() {
      if (this.plot) {
        this.resize.observe(this.plot);
        return;
      }
      this.days = JSON.parse(this.dataset.days);
      this.page = Math.ceil(this.days.length / pageSize) - 1;
      this.firstPageSize = this.days.length % pageSize || pageSize;
      this.visible = [true, true];
      this.innerHTML = `
        <div class="task-activity-header">
          <h2 class="card-title" id="task-activity-title">Сделки по дням с активностью</h2>
          <div class="task-activity-controls" role="group" aria-label="Ряды графика">
            ${series.map((label, index) => `<button type="button" data-series="${index}" aria-pressed="true"><i class="task-activity-swatch series-${index}" aria-hidden="true"></i>${label}</button>`).join('')}
          </div>
        </div>
        <div class="task-activity-plot" role="group" tabindex="0"
             aria-labelledby="task-activity-title" aria-description="Стрелки влево и вправо выбирают дату"
             aria-keyshortcuts="ArrowLeft ArrowRight Home End"></div>
        <div class="task-activity-footer">
          <div class="task-activity-detail" aria-live="polite" aria-atomic="true"></div>
          <div class="task-activity-controls task-activity-pagination" role="group" aria-label="Страницы графика">
            <button type="button" data-direction="-1">Раньше</button>
            <button type="button" data-direction="1">Позже</button>
          </div>
        </div>`;
      this.plot = this.querySelector('.task-activity-plot');
      this.detail = this.querySelector('.task-activity-detail');
      this.previous = this.querySelector('[data-direction="-1"]');
      this.next = this.querySelector('[data-direction="1"]');
      this.querySelector('.task-activity-pagination').hidden = this.days.length <= pageSize;
      this.draw();
      this.resize = new ResizeObserver(() => {
        if (this.width !== this.plot.clientWidth) this.draw(this.selected);
      });
      this.resize.observe(this.plot);
      this.plot.addEventListener('pointermove', event => this.pick(event));
      this.plot.addEventListener('click', event => this.pick(event));
      this.plot.addEventListener('keydown', event => this.navigate(event));
      this.addEventListener('click', event => {
        const button = event.target.closest('button');
        if (button?.hasAttribute('data-series')) this.toggleSeries(button);
        if (button?.hasAttribute('data-direction')) {
          this.page += Number(button.dataset.direction);
          this.draw();
          if (button.disabled) (button === this.previous ? this.next : this.previous).focus();
        }
      });
    }

    disconnectedCallback() {
      this.resize.disconnect();
    }

    draw(selected) {
      this.width = this.plot.clientWidth;
      const width = Math.max(220, this.width), height = width < 480 ? 174 : 228;
      const top = 12, base = height - 26;
      const peak = this.days.reduce((max, [, created, closed]) => Math.max(
        max, this.visible[0] ? created : 0, this.visible[1] ? closed : 0
      ), 1);
      const unit = Math.max(1, 10 ** Math.floor(Math.log10(peak / 4)));
      const step = Math.ceil(peak / (4 * unit)) * unit;
      const max = Math.ceil(peak / step) * step;
      const left = Math.max(36, count.format(max).length * 7 + 8), right = width - 8;
      const band = (right - left) / pageSize;
      const barWidth = Math.min(28, band * 0.34);
      const y = value => base - value * (base - top) / max;
      const grid = [];
      for (let value = 0; value <= max; value += step) {
        grid.push(`<path class="task-activity-grid${value === 0 ? ' base' : ''}" d="M${left} ${y(value)}H${right}"/>
          <text class="task-activity-axis" x="${left - 6}" y="${y(value) + 3}" text-anchor="end">${count.format(value)}</text>`);
      }

      const start = this.page ? this.firstPageSize + (this.page - 1) * pageSize : 0;
      const days = this.days.slice(start, start + (this.page ? pageSize : this.firstPageSize));
      const groups = days.map(([date, ...values], index) => {
        const x = left + index * band;
        const bars = values.map((value, seriesIndex) => {
          if (!value || !this.visible[seriesIndex]) return '';
          const barX = x + band / 2 + (seriesIndex ? 2 : -2 - barWidth);
          const cap = y(value), endX = barX + barWidth;
          const radius = Math.min(3, base - cap);
          return `<path class="task-activity-bar series-${seriesIndex}" d="M${barX} ${base}V${cap + radius}
            Q${barX} ${cap} ${barX + radius} ${cap}H${endX - radius}Q${endX} ${cap} ${endX} ${cap + radius}V${base}Z"/>`;
        }).join('');
        return `<g data-day="${start + index}">
          <rect class="task-activity-band" x="${x}" y="${top}" width="${band}" height="${base - top + 20}" rx="4"/>
          ${bars}
          <text class="task-activity-axis" x="${x + band / 2}" y="${base + 16}" text-anchor="middle">${shortDate.format(asDate(date))}</text>
        </g>`;
      });
      this.plot.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">${grid.join('')}${groups.join('')}</svg>`;
      this.previous.disabled = this.page === 0;
      this.next.disabled = start + days.length >= this.days.length;
      this.selectDay(selected ?? start + days.length - 1);
    }

    selectDay(index) {
      this.plot.querySelector('.is-selected')?.classList.remove('is-selected');
      this.plot.querySelector(`[data-day="${index}"]`).classList.add('is-selected');
      this.selected = index;
      const [date, ...values] = this.days[index];
      this.detail.innerHTML = `<strong>${dateLabel.format(asDate(date))}</strong>
        ${values.map((value, i) => this.visible[i]
          ? `<span><i class="task-activity-swatch series-${i}" aria-hidden="true"></i>${series[i]} <b>${count.format(value)}</b></span>`
          : '').join('')}`;
    }

    pick(event) {
      const group = event.target.closest('[data-day]');
      if (group && Number(group.dataset.day) !== this.selected) this.selectDay(Number(group.dataset.day));
    }

    navigate(event) {
      const last = this.days.length - 1;
      const targets = { ArrowLeft: this.selected - 1, ArrowRight: this.selected + 1, Home: 0, End: last };
      if (!Object.hasOwn(targets, event.key)) return;
      event.preventDefault();
      const index = Math.min(last, Math.max(0, targets[event.key]));
      const page = index < this.firstPageSize ? 0 : 1 + Math.floor((index - this.firstPageSize) / pageSize);
      if (page !== this.page) {
        this.page = page;
        this.draw();
      }
      if (index !== this.selected) this.selectDay(index);
    }

    toggleSeries(button) {
      const index = Number(button.dataset.series);
      if (button.getAttribute('aria-disabled') === 'true') return;
      const selected = this.selected;
      this.visible[index] = !this.visible[index];
      this.querySelectorAll('[data-series]').forEach((option, index) => {
        option.setAttribute('aria-pressed', this.visible[index]);
        option.setAttribute('aria-disabled', this.visible[index] && this.visible.filter(Boolean).length === 1);
      });
      this.draw(selected);
    }
  }

  customElements.define('task-analytics-chart', TaskAnalyticsChart);
})();
