// Sitni DOM alati. Bez frameworka - `el` je sve sto treba za ovoliku aplikaciju.

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);

  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }

  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function mount(node, ...children) {
  clear(node);
  node.append(...children.filter(Boolean));
  return node;
}

// ---------------------------------------------------------------- poruke

export function toast(message, kind = '') {
  const box = el('div', { class: `toast ${kind ? 'toast--' + kind : ''}`, text: message });
  $('#toasts').append(box);
  setTimeout(() => {
    box.style.transition = 'opacity .25s';
    box.style.opacity = '0';
    setTimeout(() => box.remove(), 260);
  }, kind === 'bad' ? 6500 : 3200);
}

// ---------------------------------------------------------------- modal

export function modal({ title, body, confirmText = 'Sačuvaj', cancelText = 'Otkaži', onConfirm, wide = false }) {
  const root = $('#modal-root');

  const close = () => { clear(root); document.removeEventListener('keydown', onKey); };
  const onKey = (event) => { if (event.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);

  const confirmButton = onConfirm
    ? el('button', {
        class: 'btn btn--primary',
        text: confirmText,
        onClick: async () => {
          confirmButton.disabled = true;
          try {
            const keepOpen = await onConfirm();
            if (keepOpen !== false) close();
          } finally {
            confirmButton.disabled = false;
          }
        },
      })
    : null;

  const box = el('div', { class: 'modal', style: wide ? { maxWidth: '900px' } : {} }, [
    el('div', { class: 'modal__head' }, [title]),
    el('div', { class: 'modal__body' }, [body]),
    el('div', { class: 'modal__foot' }, [
      el('button', { class: 'btn', text: onConfirm ? cancelText : 'Zatvori', onClick: close }),
      confirmButton,
    ]),
  ]);

  const backdrop = el('div', {
    class: 'modal__backdrop',
    onClick: (event) => { if (event.target === backdrop) close(); },
  }, [box]);

  mount(root, backdrop);
  const firstInput = box.querySelector('input, textarea, select');
  if (firstInput) firstInput.focus();
  return { close };
}

export function confirmDialog(title, message, confirmText = 'Obriši') {
  return new Promise((resolve) => {
    let answered = false;
    modal({
      title,
      body: el('div', { text: message }),
      confirmText,
      onConfirm: () => { answered = true; resolve(true); },
    });
    const observer = new MutationObserver(() => {
      if (!$('#modal-root').firstChild) { observer.disconnect(); if (!answered) resolve(false); }
    });
    observer.observe($('#modal-root'), { childList: true });
  });
}

// ---------------------------------------------------------------- format

export function field(label, input, hint) {
  return el('label', { class: 'field' }, [
    el('span', { class: 'field__label', text: label }),
    input,
    hint ? el('div', { class: 'field__hint', text: hint }) : null,
  ]);
}

export function bytes(value) {
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = Number(value) || 0;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size < 10 && index > 0 ? size.toFixed(1) : Math.round(size)} ${units[index]}`;
}

export function when(value) {
  if (!value) return '';
  const date = new Date(String(value).replace(' ', 'T') + (String(value).endsWith('Z') ? '' : 'Z'));
  if (Number.isNaN(date.getTime())) return String(value);
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 60) return 'upravo';
  if (diff < 3600) return `pre ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `pre ${Math.floor(diff / 3600)} h`;
  if (diff < 86400 * 7) return `pre ${Math.floor(diff / 86400)} d`;
  return date.toLocaleDateString('sr-RS');
}

export function dueIn(value) {
  if (!value) return 'novo';
  const date = new Date(String(value).replace(' ', 'T') + 'Z');
  const diff = (date.getTime() - Date.now()) / 1000;
  if (diff <= 0) return 'sada';
  if (diff < 3600) return `za ${Math.ceil(diff / 60)} min`;
  if (diff < 86400) return `za ${Math.ceil(diff / 3600)} h`;
  return `za ${Math.ceil(diff / 86400)} d`;
}

export function percent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

// Minimalni markdown - dovoljno za AI dopune, bez biblioteke.
export function markdown(text) {
  const escaped = String(text || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return escaped
    .replace(/^### (.*)$/gm, '<h3>$1</h3>')
    .replace(/^## (.*)$/gm, '<h2>$1</h2>')
    .replace(/^# (.*)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/^[-*] (.*)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
    .replace(/<\/ul>\s*<ul>/g, '')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/^/, '<p>').replace(/$/, '</p>')
    .replace(/<p>(<h[123]>)/g, '$1').replace(/(<\/h[123]>)<\/p>/g, '$1')
    .replace(/<p>(<ul>)/g, '$1').replace(/(<\/ul>)<\/p>/g, '$1');
}
