// Crtanje pitanja, tip po tip.
//
// Registar, ne if-lanac: dodavanje tipa je jedan unos ovde i jedan u
// app/quiz/types.py. Svaki renderer vraca isti ugovor:
//   { node, collect(), reveal(result) }

import { el, toast } from './dom.js';
import { api } from './api.js';

const RENDERERS = {};

export function renderQuestion(question) {
  const renderer = RENDERERS[question.type];
  if (!renderer) {
    return {
      node: el('div', { class: 'muted', text: `Nepoznat tip pitanja: ${question.type}` }),
      collect: () => ({}),
      reveal: () => {},
    };
  }
  return renderer(question);
}

const LETTERS = 'ABCDEFGHIJ';

function imageNode(image) {
  if (!image || !image.url) return null;
  return el('figure', { style: { margin: '0 0 16px' } }, [
    el('img', { class: 'question__image', src: image.url, alt: image.caption || 'slika iz materijala' }),
    image.caption ? el('figcaption', { class: 'tiny faint', text: image.caption }) : null,
  ]);
}

// ---------------------------------------------------------------- izbor

function choiceRenderer({ multiple = false } = {}) {
  return (question) => {
    const options = question.presentation.options || [];
    const picked = new Set();
    const rows = [];

    const box = el('div', { class: 'options' }, options.map((text, index) => {
      const row = el('div', { class: 'option' }, [
        el('div', { class: 'option__key', text: multiple ? '' : LETTERS[index] || String(index + 1) }),
        el('div', { class: 'option__text', text }),
      ]);
      if (multiple) {
        const check = el('input', { type: 'checkbox' });
        row.firstChild.replaceChildren(check);
        row.addEventListener('click', (event) => {
          if (event.target !== check) check.checked = !check.checked;
          check.checked ? picked.add(index) : picked.delete(index);
          row.classList.toggle('is-picked', check.checked);
        });
      } else {
        row.addEventListener('click', () => {
          picked.clear();
          picked.add(index);
          rows.forEach((item) => item.classList.remove('is-picked'));
          row.classList.add('is-picked');
        });
      }
      rows.push(row);
      return row;
    }));

    return {
      node: el('div', {}, [imageNode(question.presentation.image), box]),
      collect: () => (multiple ? { indices: [...picked] } : { index: picked.size ? [...picked][0] : null }),
      reveal: (result) => {
        const payload = result.payload || {};
        const correct = multiple
          ? new Set(payload.correct_indices || [])
          : new Set([payload.correct_index]);
        rows.forEach((row, index) => {
          row.style.pointerEvents = 'none';
          if (correct.has(index)) row.classList.add('is-right');
          else if (picked.has(index)) row.classList.add('is-wrong');
        });
      },
    };
  };
}

RENDERERS.mcq_single = choiceRenderer();
RENDERERS.odd_one_out = choiceRenderer();
RENDERERS.image_match = choiceRenderer();
RENDERERS.mcq_multi = choiceRenderer({ multiple: true });

RENDERERS.true_false = (question) => {
  let value = null;
  const buttons = [true, false].map((option) =>
    el('button', {
      class: 'btn',
      style: { flex: '1', padding: '18px', fontSize: '16px' },
      text: option ? 'TAČNO' : 'NETAČNO',
      onClick: () => {
        value = option;
        buttons.forEach((button, index) => button.classList.toggle('btn--primary', index === (option ? 0 : 1)));
      },
    }));

  return {
    node: el('div', { class: 'flex', style: { gap: '12px' } }, buttons),
    collect: () => ({ value }),
    reveal: (result) => {
      const correct = result.payload.correct ? 0 : 1;
      buttons.forEach((button, index) => {
        button.disabled = true;
        button.classList.remove('btn--primary');
        if (index === correct) button.classList.add('btn--good');
        else if (value !== null && index === (value ? 0 : 1)) button.classList.add('btn--danger');
      });
    },
  };
};

// ---------------------------------------------------------------- praznine

function blankRenderer(kind) {
  return (question) => {
    const blanks = question.presentation.blanks || [];
    const inputs = new Map();
    const parts = String(question.stem).split(/(\{\{\s*\d+\s*\}\})/g);

    const line = el('div', { class: 'question__stem', style: { marginBottom: '0' } },
      parts.map((part) => {
        const marker = part.match(/\{\{\s*(\d+)\s*\}\}/);
        if (!marker) return part;
        const id = marker[1];
        const blank = blanks.find((item) => String(item.id) === id) || { id };

        const input = kind === 'select'
          ? el('select', { class: 'blank', style: { minWidth: '150px' } }, [
              el('option', { value: '', text: '— izaberi —' }),
              ...(blank.options || []).map((text, index) => el('option', { value: String(index), text })),
            ])
          : el('input', { type: 'text', class: 'blank', placeholder: blank.hint || `${id}`,
                          autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false' });

        inputs.set(id, input);
        return input;
      }));

    return {
      node: line,
      collect: () => {
        const values = {};
        for (const [id, input] of inputs) {
          values[id] = kind === 'select'
            ? (input.value === '' ? null : Number(input.value))
            : input.value;
        }
        return { values };
      },
      reveal: (result) => {
        const perBlank = (result.detail && result.detail.per_blank) || [];
        [...inputs.entries()].forEach(([, input], index) => {
          input.disabled = true;
          const ok = perBlank[index];
          input.style.borderBottomColor = ok ? 'var(--good)' : 'var(--bad)';
          input.style.background = ok ? 'var(--good-soft)' : 'var(--bad-soft)';
        });
      },
    };
  };
}

RENDERERS.fill_blank = blankRenderer('text');
RENDERERS.cloze_dropdown = blankRenderer('select');

// ---------------------------------------------------------------- tekst

function textRenderer({ rows = 3, placeholder = 'Tvoj odgovor...' } = {}) {
  return () => {
    const input = el('textarea', { rows, placeholder });
    return {
      node: input,
      collect: () => ({ text: input.value }),
      reveal: () => { input.disabled = true; },
    };
  };
}

RENDERERS.short_answer = textRenderer({ rows: 2 });
RENDERERS.long_answer = textRenderer({ rows: 7, placeholder: 'Napiši rešenje ili objašnjenje...' });

RENDERERS.numeric = (question) => {
  const input = el('input', { type: 'text', inputmode: 'decimal', placeholder: '0',
                              style: { maxWidth: '220px', fontSize: '18px' } });
  const unit = question.presentation.unit;
  return {
    node: el('div', { class: 'flex' }, [
      input,
      unit ? el('span', { class: 'muted', text: unit }) : null,
    ]),
    collect: () => ({ value: input.value }),
    reveal: () => { input.disabled = true; },
  };
};

// ---------------------------------------------------------------- parovi

RENDERERS.match_pairs = (question) => {
  const left = question.presentation.left || [];
  const right = question.presentation.right || [];
  const selects = [];

  const node = el('div', { class: 'pairs' }, left.map((text, index) => {
    const select = el('select', {}, [
      el('option', { value: '', text: '— izaberi —' }),
      ...right.map((option, position) => el('option', { value: String(position), text: option })),
    ]);
    selects.push(select);
    return el('div', { class: 'pair' }, [
      el('div', { class: 'pair__left', text }),
      el('div', { class: 'pair__arrow', text: '→' }),
      select,
    ]);
  }));

  return {
    node,
    collect: () => ({ mapping: selects.map((select) => (select.value === '' ? null : Number(select.value))) }),
    reveal: (result) => {
      const perPair = (result.detail && result.detail.per_pair) || [];
      selects.forEach((select, index) => {
        select.disabled = true;
        select.style.borderColor = perPair[index] ? 'var(--good)' : 'var(--bad)';
      });
    },
  };
};

RENDERERS.order_sequence = (question) => {
  const items = question.presentation.items || [];
  let order = items.map((_, index) => index);
  const list = el('div', { class: 'sortable' });

  const draw = () => {
    list.replaceChildren(...order.map((itemIndex, position) =>
      el('div', { class: 'sortable__item' }, [
        el('div', { class: 'sortable__ordinal', text: String(position + 1) }),
        el('div', { class: 'sortable__text', text: items[itemIndex] }),
        el('div', { class: 'sortable__moves' }, [
          el('button', { class: 'btn btn--sm btn--ghost', text: '↑', disabled: position === 0,
                         onClick: () => { swap(position, position - 1); } }),
          el('button', { class: 'btn btn--sm btn--ghost', text: '↓', disabled: position === order.length - 1,
                         onClick: () => { swap(position, position + 1); } }),
        ]),
      ])));
  };
  const swap = (a, b) => { [order[a], order[b]] = [order[b], order[a]]; draw(); };
  draw();

  return {
    node: el('div', {}, [
      el('div', { class: 'tiny faint mb1', text: 'Poređaj strelicama u tačan redosled.' }),
      list,
    ]),
    collect: () => ({ order }),
    reveal: () => { list.querySelectorAll('button').forEach((button) => { button.disabled = true; }); },
  };
};

// ---------------------------------------------------------------- slika

RENDERERS.image_label = (question) => {
  const image = question.presentation.image || {};
  const targets = question.presentation.targets || [];
  const marks = new Map();
  let active = targets.length ? targets[0].id : null;

  const layer = el('div', { class: 'hotspot' });
  const picture = el('img', { src: image.url || '', alt: image.caption || 'slika' });
  layer.append(picture);

  layer.addEventListener('click', (event) => {
    if (active === null) return;
    const box = picture.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width;
    const y = (event.clientY - box.top) / box.height;
    marks.set(active, { id: active, x, y });
    drawMarks();
    const next = targets.find((target) => !marks.has(target.id));
    active = next ? next.id : null;
    drawChips();
  });

  const drawMarks = () => {
    layer.querySelectorAll('.hotspot__mark').forEach((node) => node.remove());
    for (const [id, mark] of marks) {
      const index = targets.findIndex((target) => target.id === id);
      layer.append(el('div', {
        class: 'hotspot__mark',
        dataset: { id: String(id) },
        style: { left: `${mark.x * 100}%`, top: `${mark.y * 100}%` },
        text: String(index + 1),
      }));
    }
  };

  const chips = el('div', { class: 'btn-row mb1' });
  const drawChips = () => {
    chips.replaceChildren(...targets.map((target, index) =>
      el('button', {
        class: `tool ${active === target.id ? 'is-on' : ''}`,
        text: `${index + 1}. ${target.label}${marks.has(target.id) ? ' ✓' : ''}`,
        onClick: () => { active = target.id; drawChips(); },
      })));
  };
  drawChips();

  return {
    node: el('div', {}, [
      el('div', { class: 'tiny faint mb1', text: 'Izaberi pojam pa klikni gde je na slici.' }),
      chips, layer,
    ]),
    collect: () => ({ marks: [...marks.values()] }),
    reveal: (result) => {
      const perTarget = (result.detail && result.detail.per_target) || [];
      layer.style.pointerEvents = 'none';
      targets.forEach((target, index) => {
        const node = layer.querySelector(`.hotspot__mark[data-id="${target.id}"]`);
        if (node) node.classList.add(perTarget[index] ? 'is-right' : 'is-wrong');
      });
    },
  };
};

// ---------------------------------------------------------------- ostalo

RENDERERS.work_it_out = (question) => {
  const text = el('textarea', { rows: 3, placeholder: 'Konačan rezultat ili kratak postupak...' });
  const preview = el('div', { class: 'mt1' });
  let photoPath = null;

  const picker = el('input', {
    type: 'file', accept: 'image/*', capture: 'environment', class: 'hidden',
    onChange: async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      const form = new FormData();
      form.append('photo', file, file.name);
      try {
        const response = await fetch(`/api/study/photo/${question.id}`, { method: 'POST', body: form });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) throw new Error(payload.error || 'Slanje nije uspelo.');
        photoPath = payload.photo_path;
        preview.replaceChildren(el('img', { class: 'question__image', src: payload.url, alt: 'tvoje rešenje' }));
      } catch (error) {
        toast(error.message, 'bad');
      }
    },
  });

  return {
    node: el('div', {}, [
      el('div', { class: 'tiny faint mb1',
                  text: 'Uradi na papiru, slikaj telefonom i pošalji — AI proverava postupak.' }),
      text,
      el('div', { class: 'btn-row mt1' }, [
        el('button', { class: 'btn', text: '📷 Slikaj / dodaj sliku', onClick: () => picker.click() }),
        picker,
      ]),
      preview,
    ]),
    collect: () => ({ text: text.value, photo_path: photoPath }),
    reveal: () => { text.disabled = true; },
  };
};

RENDERERS.flashcard = (question) => {
  let known = null;
  // Poledjina stize uz pitanje (`presentation.back`) bas zato sto se korisnik
  // ocenjuje sam: "znao sam / nisam znao" nema smisla dok odgovor ne vidi.
  const answerText = question.presentation.back || '';
  const answerNode = el('div', { class: 'prose', text: answerText });
  const back = el('div', { class: 'card mt1 hidden' }, [
    el('div', { class: 'card__body' }, [
      el('div', { class: 'field__label', text: 'Tačan odgovor' }),
      answerNode,
    ]),
  ]);
  const buttons = el('div', { class: 'btn-row mt1 hidden' });

  const flip = el('button', {
    class: 'btn btn--primary',
    text: 'Okreni karticu',
    onClick: () => {
      flip.classList.add('hidden');
      back.classList.remove('hidden');
      buttons.classList.remove('hidden');
    },
  });

  const grade = (value) => {
    known = value;
    buttons.dispatchEvent(new CustomEvent('answered', { bubbles: true }));
  };

  buttons.append(
    el('div', { class: 'tiny faint', style: { width: '100%' }, text: 'Da li si znao ovaj odgovor?' }),
    el('button', { class: 'btn btn--good', text: 'Znao sam', onClick: () => grade(true) }),
    el('button', { class: 'btn btn--danger', text: 'Nisam znao', onClick: () => grade(false) }),
  );

  return {
    node: el('div', {}, [flip, back, buttons]),
    collect: () => ({ known }),
    reveal: () => {
      // Odgovor ostaje na ekranu; sklanjaju se samo dugmad za samoocenjivanje.
      back.classList.remove('hidden');
      buttons.classList.add('hidden');
      flip.classList.add('hidden');
    },
    autoSubmitOn: 'answered',
  };
};
