# Composite the computed CSS colors so transparent labels use the card fill.
TEXT_CONTRAST_FAILURES = '''els => {
  const ctx = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  const luminance = () => [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3)
    .map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((total, v, i) => total + v * [.2126, .7152, .0722][i], 0);
  const fill = color => { ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); };
  return els.map(el => {
    const layers = [];
    for (let node = el; node; node = node.parentElement) layers.unshift(getComputedStyle(node));
    ctx.clearRect(0, 0, 1, 1);
    layers.forEach(style => fill(style.backgroundColor));
    const paper = luminance();
    fill(getComputedStyle(el).color);
    const ink = luminance();
    return {text: (el.textContent || el.getAttribute('aria-label') || '').trim(),
      ratio: (Math.max(paper, ink) + .05) / (Math.min(paper, ink) + .05)};
  }).filter(item => item.ratio < 4.5);
}'''
