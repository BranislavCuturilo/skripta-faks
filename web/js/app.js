// Ulazna tačka: stablo u sidebar-u, rutiranje preko hash-a, tabovi predmeta.

import { api } from './api.js';
import { $, el, mount, clear, modal, field, toast, confirmDialog } from './dom.js';
import {
  store, bootstrap, subscribe, reloadTree, findCategory,
  flattenTree, toggleExpanded, expandTo,
} from './store.js';
import { overview, materials, generate } from './views/category.js';
import { questions, strategy, notes } from './views/library.js';
import { settings } from './views/settings.js';
import { studySetup, runSession } from './views/study.js';
import { guide } from './views/guide.js';
import { proposals } from './views/proposals.js';
import { networkCard } from './views/network.js';

const TABS = [
  ['pregled', 'Pregled'],
  ['uci', 'Uči'],
  ['pitanja', 'Pitanja'],
  ['materijali', 'Materijali'],
  ['generisanje', 'Generisanje'],
  ['strategija', 'Strategija'],
  ['dopune', 'Dopune'],
];

const view = () => $('#view');

// ---------------------------------------------------------------- stablo

function drawTree() {
  const root = $('#tree');
  if (!store.tree.length) {
    mount(root, el('div', { class: 'empty' }, [
      el('div', { class: 'empty__title', text: 'Nema predmeta' }),
      el('div', { class: 'tiny', text: 'Napravi prvi ispod.' }),
    ]));
    return;
  }
  mount(root, ...store.tree.map(treeNode));
}

function treeNode(node) {
  const hasChildren = (node.children || []).length > 0;
  const open = store.expanded.has(node.id);

  const row = el('div', {
    class: `tree__row ${store.categoryId === node.id ? 'is-active' : ''}`,
    onClick: () => go(node.id, store.categoryId === node.id ? store.tab : 'pregled'),
    oncontextmenu: (event) => { event.preventDefault(); categoryMenu(node); },
  }, [
    el('span', {
      class: `tree__caret ${open ? 'is-open' : ''} ${hasChildren ? '' : 'is-leaf'}`,
      text: '▶',
      onClick: (event) => { event.stopPropagation(); toggleExpanded(node.id); drawTree(); },
    }),
    el('span', { class: 'tree__name', text: node.name, title: node.name }),
    node.total_due
      ? el('span', { class: 'tree__count is-due', title: 'na redu za ponavljanje', text: String(node.total_due) })
      : el('span', { class: 'tree__count', text: node.total_questions ? String(node.total_questions) : '' }),
  ]);

  return el('div', { class: 'tree__item' }, [
    row,
    hasChildren && open
      ? el('div', { class: 'tree__children' }, node.children.map(treeNode))
      : null,
  ]);
}

function categoryMenu(node) {
  const name = el('input', { type: 'text', value: node.name });
  modal({
    title: node.name,
    confirmText: 'Sačuvaj',
    body: el('div', {}, [
      field('Naziv', name),
      el('div', { class: 'btn-row mt2' }, [
        el('button', {
          class: 'btn btn--sm', text: '+ Podkategorija',
          onClick: () => { clear($('#modal-root')); newCategory(node.id); },
        }),
        el('button', {
          class: 'btn btn--sm', text: 'Premesti u koren',
          disabled: !node.parent_id,
          onClick: async () => {
            await api.post(`/api/categories/${node.id}/move`, { parent_id: null });
            clear($('#modal-root'));
            reloadTree();
          },
        }),
        el('button', {
          class: 'btn btn--sm btn--danger', text: 'Obriši',
          onClick: async () => {
            clear($('#modal-root'));
            const ok = await confirmDialog(
              `Obrisati "${node.name}"?`,
              'Briše se sa svim podkategorijama, materijalima i pitanjima. Ovo se ne vraća.',
            );
            if (!ok) return;
            await api.del(`/api/categories/${node.id}?confirm=1`);
            toast('Obrisano');
            if (store.categoryId === node.id) { store.categoryId = null; location.hash = ''; }
            reloadTree();
          },
        }),
      ]),
    ]),
    onConfirm: async () => {
      await api.patch(`/api/categories/${node.id}`, { name: name.value });
      reloadTree();
    },
  });
}

function newCategory(parentId = null) {
  const name = el('input', { type: 'text', placeholder: parentId ? 'npr. Kolokvijum 1' : 'npr. Matematika 2' });
  const prompt = el('textarea', {
    rows: 4,
    placeholder: 'Npr. "Uči se samo do lekcije 5, bez dokaza teorema."',
  });

  modal({
    title: parentId ? 'Nova podkategorija' : 'Novi predmet',
    confirmText: 'Napravi',
    body: el('div', {}, [
      field('Naziv', name),
      field('Šta se tačno uči (može i kasnije)', prompt,
            'Ovo uputstvo ide u svaki prompt i ograničava obim gradiva.'),
    ]),
    onConfirm: async () => {
      if (!name.value.trim()) { toast('Naziv je obavezan.', 'bad'); return false; }
      const payload = await api.post('/api/categories', {
        name: name.value, parent_id: parentId, study_prompt: prompt.value,
      });
      await reloadTree();
      if (parentId) expandTo(payload.category.id);
      go(payload.category.id, 'materijali');
    },
  });
}

// ---------------------------------------------------------------- rutiranje

function go(categoryId, tab = 'pregled') {
  location.hash = categoryId ? `#/k/${categoryId}/${tab}` : '#/podesavanja';
}

async function route() {
  const hash = location.hash.replace(/^#\/?/, '');
  const parts = hash.split('/').filter(Boolean);
  closeMenu();

  const standalone = {
    podesavanja: ['Podešavanja', '', settings],
    uputstvo: ['Uputstvo', 'od nule do prve sesije', guide],
    predlozi: ['Predlozi za nadogradnju', 'kad ti aplikacija ne radi ono što ti treba', proposals],
  };
  if (standalone[parts[0]]) {
    const [title, subtitle, screen] = standalone[parts[0]];
    store.categoryId = null;
    drawTree();
    setTitle(title, subtitle);
    mount($('#topbar-actions'));
    return screen(view());
  }

  if (parts[0] === 'k' && parts[1]) {
    const categoryId = Number(parts[1]);
    const tab = parts[2] || 'pregled';
    store.categoryId = categoryId;
    store.tab = tab;
    expandTo(categoryId);
    drawTree();
    return drawCategory(categoryId, tab);
  }

  store.categoryId = null;
  drawTree();
  return home();
}

function setTitle(title, subtitle) {
  mount($('#page-title'),
    document.createTextNode(title),
    subtitle ? el('small', { text: subtitle }) : null);
}

async function drawCategory(categoryId, tab) {
  let detail;
  try {
    detail = await api.get(`/api/categories/${categoryId}`);
  } catch (error) {
    toast(error.message, 'bad');
    location.hash = '';
    return;
  }

  const path = detail.breadcrumb.map((node) => node.name).join(' / ');
  setTitle(detail.category.name, detail.breadcrumb.length > 1 ? path : '');

  mount($('#topbar-actions'),
    el('button', { class: 'btn btn--sm', text: '+ Podkategorija',
                   onClick: () => newCategory(categoryId) }),
    el('button', { class: 'btn btn--sm btn--primary', text: '▶ Uči',
                   onClick: () => go(categoryId, 'uci') }));

  const body = el('div');
  mount(view(),
    el('div', { class: 'tabs' }, TABS.map(([key, label]) =>
      el('button', {
        class: `tabs__item ${tab === key ? 'is-active' : ''}`,
        text: label,
        onClick: () => go(categoryId, key),
      }))),
    body);

  const screens = {
    pregled: () => overview(body, categoryId, (next) => go(categoryId, next)),
    materijali: () => materials(body, categoryId),
    generisanje: () => generate(body, categoryId),
    pitanja: () => questions(body, categoryId),
    strategija: () => strategy(body, categoryId),
    dopune: () => notes(body, categoryId),
    uci: () => studyScreen(body, categoryId),
  };
  try {
    await (screens[tab] || screens.pregled)();
  } catch (error) {
    mount(body, el('div', { class: 'empty' }, [
      el('div', { class: 'empty__title', text: 'Greška pri učitavanju' }),
      el('div', { text: error.message }),
    ]));
  }
}

function studyScreen(body, categoryId) {
  studySetup(body, categoryId, (sessionId) => {
    runSession(body, sessionId, (again) => {
      if (again) studyScreen(body, categoryId);
      else go(categoryId, 'pregled');
    });
  });
}

async function home() {
  setTitle('skripta-faks', 'lokalno učenje uz AI');
  mount($('#topbar-actions'));

  const stats = store.stats || {};
  const flat = flattenTree().filter((node) => node.total_due > 0)
    .sort((a, b) => b.total_due - a.total_due);

  mount(view(),
    el('div', { class: 'grid mb2' }, [
      tile(stats.categories, 'kategorija'),
      tile(stats.materials, 'materijala'),
      tile(stats.questions, 'pitanja'),
      tile(stats.due_now, 'na redu sada', 'due'),
    ]),

    await networkCard({ compact: store.tree.length > 0 }),

    flat.length
      ? el('div', { class: 'card' }, [
          el('div', { class: 'card__head' }, ['Na redu za ponavljanje']),
          el('div', { class: 'list' }, flat.slice(0, 10).map((node) =>
            el('div', { class: 'list__row' }, [
              el('div', { class: 'list__main' }, [
                el('div', { class: 'list__title', text: node.name }),
                el('div', { class: 'list__meta', text: `${node.total_questions} pitanja ukupno` }),
              ]),
              el('span', { class: 'badge badge--warn', text: `${node.total_due} na redu` }),
              el('button', { class: 'btn btn--sm btn--primary', text: 'Uči',
                             onClick: () => go(node.id, 'uci') }),
            ]))),
        ])
      : null,

    !store.tree.length
      ? el('div', { class: 'card' }, [
          el('div', { class: 'card__head' }, ['Kako da počneš']),
          el('div', { class: 'card__body' }, [
            el('ol', { class: 'prose' }, [
              el('li', { text: 'Otvori Podešavanja i unesi besplatan Gemini API ključ.' }),
              el('li', { text: 'Napravi predmet (npr. "Matematika 2"), pa u njemu podkategoriju ("Kolokvijum 1").' }),
              el('li', { text: 'U tab Materijali ubaci skriptu, slajdove, slike table, snimke.' }),
              el('li', { text: 'U Pregledu napiši šta se tačno uči — npr. "samo do lekcije 5".' }),
              el('li', { text: 'U tab Generisanje pritisni Generiši. Onda Uči.' }),
            ]),
            el('div', { class: 'btn-row mt2' }, [
              el('button', { class: 'btn btn--primary', text: '+ Napravi prvi predmet',
                             onClick: () => newCategory(null) }),
              el('button', { class: 'btn', text: '❓ Detaljno uputstvo',
                             onClick: () => { location.hash = '#/uputstvo'; } }),
              el('button', { class: 'btn', text: '⚙ Podešavanja',
                             onClick: () => { location.hash = '#/podesavanja'; } }),
            ]),
          ]),
        ])
      : null,

    !store.settings.gemini_api_key_set && store.tree.length
      ? el('div', { class: 'card' }, [
          el('div', { class: 'card__body flex-between' }, [
            el('div', { text: 'Gemini API ključ još nije unet — generisanje pitanja i AI ocenjivanje ne rade.' }),
            el('button', { class: 'btn btn--primary nowrap', text: 'Unesi ključ',
                           onClick: () => { location.hash = '#/podesavanja'; } }),
          ]),
        ])
      : null,
  );
}

function tile(value, label, kind = '') {
  return el('div', { class: `stat ${kind ? 'stat--' + kind : ''}` }, [
    el('div', { class: 'stat__value', text: String(value ?? 0) }),
    el('div', { class: 'stat__label', text: label }),
  ]);
}

// ---------------------------------------------------------------- mobilni meni

function openMenu() {
  $('#sidebar').classList.add('is-open');
  if (!$('.scrim')) {
    document.body.append(el('div', { class: 'scrim', onClick: closeMenu }));
  }
}
function closeMenu() {
  $('#sidebar').classList.remove('is-open');
  $('.scrim')?.remove();
}

// ---------------------------------------------------------------- start

async function start() {
  $('#new-category').onclick = () => newCategory(null);
  $('#open-settings').onclick = () => { location.hash = '#/podesavanja'; };
  $('#open-guide').onclick = () => { location.hash = '#/uputstvo'; };
  $('#open-proposals').onclick = () => { location.hash = '#/predlozi'; };
  $('#menu-toggle').onclick = () => {
    $('#sidebar').classList.contains('is-open') ? closeMenu() : openMenu();
  };

  window.addEventListener('hashchange', route);
  subscribe(drawTree);

  try {
    await bootstrap();
  } catch (error) {
    mount(view(), el('div', { class: 'empty' }, [
      el('div', { class: 'empty__title', text: 'Server ne odgovara' }),
      el('div', { text: error.message }),
    ]));
    return;
  }
  route();
}

start();
