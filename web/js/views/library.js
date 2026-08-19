// Pitanja, strategija i dopune - sve što se gleda van sesije učenja.

import { api } from '../api.js';
import { el, mount, modal, field, toast, when, dueIn, percent, markdown, confirmDialog } from '../dom.js';
import { store, typeLabel, reloadTree } from '../store.js';

// ---------------------------------------------------------------- pitanja

export async function questions(root, categoryId) {
  const filters = { q: '', type: '', flag: '', subtree: 1 };
  const listBox = el('div');

  const search = el('input', {
    type: 'search', placeholder: 'Traži po tekstu pitanja ili temi...',
    onInput: debounce((event) => { filters.q = event.target.value; draw(); }, 250),
  });

  const typeSelect = el('select', {
    onChange: (event) => { filters.type = event.target.value; draw(); },
  }, [el('option', { value: '', text: 'Svi tipovi' }),
      ...store.questionTypes.map((item) => el('option', { value: item.key, text: item.label }))]);

  const flagSelect = el('select', {
    onChange: (event) => { filters.flag = event.target.value; draw(); },
  }, [
    el('option', { value: '', text: 'Sve oznake' }),
    el('option', { value: 'flag_review', text: '🚩 Za proveru' }),
    el('option', { value: 'flag_check_source', text: '🔍 Provera u fajlu' }),
    el('option', { value: 'flag_irrelevant', text: '🗑 Nebitno' }),
    el('option', { value: 'noted', text: '📝 Ima belešku' }),
    el('option', { value: 'ignored', text: '🚫 Zanemareno' }),
  ]);

  async function draw() {
    mount(listBox, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Učitavam...']));
    const query = new URLSearchParams({
      q: filters.q, type: filters.type, flag: filters.flag,
      subtree: String(filters.subtree), limit: '200',
    });
    const payload = await api.get(`/api/categories/${categoryId}/questions?${query}`);

    if (!payload.items.length) {
      mount(listBox, el('div', { class: 'empty' }, [
        el('div', { class: 'empty__title', text: 'Nema pitanja po ovom filteru' }),
        el('div', { text: filters.q || filters.type || filters.flag
          ? 'Ublaži filter.' : 'Generiši pitanja iz materijala u tabu Generisanje.' }),
      ]));
      return;
    }

    mount(listBox,
      el('div', { class: 'small muted mb1', text: `${payload.items.length} od ${payload.total}` }),
      el('div', { class: 'list' }, payload.items.map((item) => questionRow(item, draw))));
  }

  mount(root,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__body' }, [
        el('div', { class: 'row2' }, [search, el('div', { class: 'flex' }, [typeSelect, flagSelect])]),
        el('label', { class: 'checkline mt1' }, [
          el('input', { type: 'checkbox', checked: true,
                        onChange: (event) => { filters.subtree = event.target.checked ? 1 : 0; draw(); } }),
          'Uključi podkategorije',
        ]),
      ]),
    ]),
    listBox);

  draw();
}

function questionRow(item, refresh) {
  const flags = [];
  if (item.origin === 'exam') flags.push(el('span', { class: 'badge badge--accent', title: 'doslovno iz ispitne baze', text: 'ispit 1:1' }));
  if (item.flags.flag_review) flags.push(el('span', { class: 'badge badge--warn', text: '🚩' }));
  if (item.flags.flag_check_source) flags.push(el('span', { class: 'badge badge--warn', text: '🔍' }));
  if (item.flags.flag_irrelevant) flags.push(el('span', { class: 'badge', text: '🗑' }));
  if (item.note) flags.push(el('span', { class: 'badge badge--accent', text: '📝' }));
  if (item.ignored) flags.push(el('span', { class: 'badge badge--bad', text: 'zanemareno' }));

  const mastery = item.progress.seen
    ? el('span', {
        class: `badge ${item.progress.mastery >= 0.85 ? 'badge--good'
          : (item.progress.mastery >= 0.5 ? 'badge--warn' : 'badge--bad')}`,
        title: `viđeno ${item.progress.seen}×, tačno ${item.progress.correct}×`,
        text: percent(item.progress.mastery),
      })
    : el('span', { class: 'badge', text: 'novo' });

  return el('div', { class: 'list__row' }, [
    el('div', { class: 'list__main', style: { cursor: 'pointer' },
                onClick: () => openQuestion(item, refresh) }, [
      el('div', { class: 'list__title', text: item.stem }),
      el('div', { class: 'list__meta',
                  text: `${typeLabel(item.type)}${item.topic ? ' · ' + item.topic : ''}` +
                        ` · sledeći put ${dueIn(item.progress.due_at)}` }),
    ]),
    ...flags,
    mastery,
  ]);
}

function openQuestion(item, refresh) {
  const noteInput = el('textarea', { rows: 3, text: item.note || '',
                                     placeholder: 'Tvoja beleška uz ovo pitanje...' });

  const flagRow = (key, label) => el('label', { class: 'checkline' }, [
    el('input', { type: 'checkbox', checked: item.flags[key],
                  onChange: (event) => { item.flags[key] = event.target.checked; } }),
    label,
  ]);

  modal({
    wide: true,
    title: typeLabel(item.type),
    confirmText: 'Sačuvaj',
    body: el('div', {}, [
      el('div', { class: 'question__stem', style: { fontSize: '17px' }, text: item.stem }),
      el('div', { class: 'card' }, [
        el('div', { class: 'card__head' }, ['Tačan odgovor']),
        el('div', { class: 'card__body' }, [
          el('div', { text: item.correct_text || '—' }),
          item.explanation
            ? el('div', { class: 'prose small mt1', html: markdown(item.explanation) })
            : null,
        ]),
      ]),
      el('div', { class: 'row2' }, [
        el('div', {}, [
          el('div', { class: 'field__label', text: 'Oznake' }),
          flagRow('flag_review', '🚩 Želim ovo da proverim'),
          flagRow('flag_check_source', '🔍 Proveriti u fajlu (ponavlja se ili je greška)'),
          flagRow('flag_irrelevant', '🗑 Nebitno, za uklanjanje'),
          el('label', { class: 'checkline' }, [
            el('input', { type: 'checkbox', checked: item.ignored,
                          onChange: (event) => { item.ignored = event.target.checked; } }),
            '🚫 Zanemari zauvek (ne pitaj me više)',
          ]),
        ]),
        el('div', {}, [
          el('div', { class: 'field__label', text: 'Beleška' }),
          noteInput,
          el('div', { class: 'field__hint',
                      text: `Viđeno ${item.progress.seen}×, tačno ${item.progress.correct}×.` +
                            (item.source_ref ? ` Izvor: ${item.source_ref}.` : '') }),
        ]),
      ]),
      el('div', { class: 'btn-row' }, [
        el('button', { class: 'btn btn--sm', text: 'Izmeni tekst pitanja',
                       onClick: () => editQuestion(item, refresh) }),
        el('button', {
          class: 'btn btn--sm btn--danger', text: 'Obriši trajno',
          onClick: async () => {
            if (!await confirmDialog('Obrisati pitanje?', 'Briše se zajedno sa istorijom odgovora.')) return;
            await api.del(`/api/questions/${item.id}`);
            toast('Obrisano');
            reloadTree();
            refresh();
          },
        }),
      ]),
    ]),
    onConfirm: async () => {
      await api.post(`/api/questions/${item.id}/meta`, {
        note: noteInput.value,
        flag_review: item.flags.flag_review,
        flag_check_source: item.flags.flag_check_source,
        flag_irrelevant: item.flags.flag_irrelevant,
        ignored: item.ignored,
      });
      toast('Sačuvano', 'good');
      refresh();
    },
  });
}

function editQuestion(item, refresh) {
  const stem = el('textarea', { rows: 3, text: item.stem });
  const explanation = el('textarea', { rows: 3, text: item.explanation });
  const payload = el('textarea', { class: 'mono', rows: 8,
                                   text: JSON.stringify(item.payload, null, 2) });

  modal({
    wide: true,
    title: 'Izmena pitanja',
    confirmText: 'Sačuvaj izmenu',
    body: el('div', {}, [
      field('Tekst pitanja', stem),
      field('Objašnjenje', explanation),
      field('Odgovori (JSON)', payload,
            'Prolazi kroz istu proveru kao AI izlaz — neispravan oblik neće biti sačuvan.'),
    ]),
    onConfirm: async () => {
      let parsed;
      try {
        parsed = JSON.parse(payload.value);
      } catch (error) {
        toast('JSON nije ispravan: ' + error.message, 'bad');
        return false;
      }
      try {
        await api.patch(`/api/questions/${item.id}`,
                        { stem: stem.value, explanation: explanation.value, payload: parsed });
        toast('Izmenjeno', 'good');
        refresh();
      } catch (error) {
        toast(error.message, 'bad');
        return false;
      }
    },
  });
}

// ---------------------------------------------------------------- strategija

export async function strategy(root, categoryId) {
  mount(root, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Učitavam...']));
  const payload = await api.get(`/api/categories/${categoryId}/strategy`);
  const content = payload.active.content || {};

  const refreshButton = el('button', {
    class: 'btn btn--primary', text: '🔄 Neka AI predloži novu strategiju',
    onClick: async () => {
      refreshButton.disabled = true;
      try {
        const result = await api.post(`/api/categories/${categoryId}/strategy/refresh`);
        if (result.skipped) toast(result.reason, 'bad');
        else toast('Strategija je osvežena', 'good');
        strategy(root, categoryId);
      } catch (error) {
        toast(error.message, 'bad');
        refreshButton.disabled = false;
      }
    },
  });

  mount(root,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, [
        'Kako te sistem trenutno ispituje',
        el('small', { text: payload.active.version ? `verzija ${payload.active.version}` : 'podrazumevano' }),
      ]),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'small muted mb2',
                    text: 'Ovo je ono što aplikacija menja o sebi: raspodelu tipova, težinu i teme u fokusu. ' +
                          'Sadržaj živi u bazi — kod aplikacije se ne dira nikad.' }),

        Object.keys(content.type_mix || {}).length
          ? el('div', { class: 'mb2' }, [
              el('div', { class: 'field__label', text: 'Raspodela tipova' }),
              el('div', { class: 'btn-row' }, Object.entries(content.type_mix).map(([key, weight]) =>
                el('span', { class: 'badge badge--accent', text: `${typeLabel(key)} ×${weight}` }))),
            ])
          : null,

        (content.focus_topics || []).length
          ? el('div', { class: 'mb2' }, [
              el('div', { class: 'field__label', text: 'Teme u fokusu' }),
              el('div', { class: 'btn-row' }, content.focus_topics.map((topic) =>
                el('span', { class: 'badge badge--warn', text: topic }))),
            ])
          : null,

        content.difficulty_bias
          ? el('div', { class: 'mb1',
                        text: `Težina: ${content.difficulty_bias > 0 ? 'teža nego inače' : 'lakša nego inače'}` })
          : null,

        content.generation_note
          ? el('div', { class: 'mb2' }, [
              el('div', { class: 'field__label', text: 'Dodatno uputstvo u promptu' }),
              el('div', { class: 'small', text: content.generation_note }),
            ])
          : null,

        payload.active.rationale
          ? el('div', { class: 'feedback feedback--partial' }, [
              el('div', { class: 'feedback__verdict', text: 'Zašto ovako' }),
              el('div', { class: 'feedback__body', text: payload.active.rationale }),
            ])
          : el('div', { class: 'muted small', text: 'Još nema prilagođene strategije — koristi se podrazumevana.' }),

        el('div', { class: 'btn-row mt2' }, [refreshButton]),
      ]),
    ]),

    payload.misconceptions.length
      ? el('div', { class: 'card' }, [
          el('div', { class: 'card__head' }, ['Greške koje ponavljaš']),
          el('div', { class: 'list' }, payload.misconceptions.map((item) =>
            el('div', { class: 'list__row' }, [
              el('div', { class: 'list__main' }, [
                el('div', { class: 'list__title', text: item.label }),
                item.description ? el('div', { class: 'list__meta', text: item.description }) : null,
              ]),
              el('span', { class: 'badge badge--bad', text: `${item.evidence_count}×` }),
              el('button', {
                class: 'btn btn--sm btn--ghost', text: '✓', title: 'Rešeno, skloni sa liste',
                onClick: async () => {
                  await api.post(`/api/misconceptions/${item.id}/resolve`, { resolved: true });
                  strategy(root, categoryId);
                },
              }),
            ]))),
        ])
      : null,

    payload.history.length > 1
      ? el('div', { class: 'card' }, [
          el('div', { class: 'card__head' }, ['Istorija izmena', el('small', { text: 'svaka se vraća' })]),
          el('div', { class: 'list' }, payload.history.map((item) =>
            el('div', { class: 'list__row' }, [
              el('div', { class: 'list__main' }, [
                el('div', { class: 'list__title', text: `Verzija ${item.version} · ${item.author}` }),
                el('div', { class: 'list__meta', text: `${when(item.created_at)} · ${item.rationale || ''}` }),
              ]),
              item.active
                ? el('span', { class: 'badge badge--good', text: 'aktivna' })
                : el('button', {
                    class: 'btn btn--sm', text: 'Vrati',
                    onClick: async () => {
                      await api.post(`/api/strategy/${item.id}/revert`);
                      toast('Vraćeno na tu verziju', 'good');
                      strategy(root, categoryId);
                    },
                  }),
            ]))),
        ])
      : null,

    evidenceCard(payload.evidence),
  );
}

function evidenceCard(evidence) {
  const weak = evidence.weakest_topics || [];
  if (!weak.length && !(evidence.by_type || []).length) return null;

  return el('div', { class: 'card' }, [
    el('div', { class: 'card__head' }, ['Na osnovu čega', el('small', { text: 'tvoji rezultati' })]),
    el('div', { class: 'card__body' }, [
      weak.length
        ? el('div', { class: 'mb2' }, [
            el('div', { class: 'field__label', text: 'Najslabije teme' }),
            el('div', { class: 'list' }, weak.slice(0, 8).map((item) =>
              el('div', { class: 'list__row' }, [
                el('div', { class: 'list__main', text: item.topic }),
                el('span', { class: 'badge', text: `${item.attempts}×` }),
                el('span', {
                  class: `badge ${item.average_score >= 0.8 ? 'badge--good' : 'badge--bad'}`,
                  text: percent(item.average_score),
                }),
              ]))),
          ])
        : null,
      (evidence.by_type || []).length
        ? el('div', {}, [
            el('div', { class: 'field__label', text: 'Po tipu zadatka' }),
            el('div', { class: 'btn-row' }, evidence.by_type.map((item) =>
              el('span', {
                class: `badge ${item.average_score >= 0.8 ? 'badge--good' : 'badge--warn'}`,
                text: `${typeLabel(item.type)} ${percent(item.average_score)}`,
              }))),
          ])
        : null,
    ]),
  ]);
}

// ---------------------------------------------------------------- dopune

export async function notes(root, categoryId) {
  mount(root, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Učitavam...']));
  const { notes: rows } = await api.get(`/api/categories/${categoryId}/notes`);

  const generateButton = el('button', {
    class: 'btn btn--primary', text: '✨ Neka AI napiše dopunu za moje rupe',
    onClick: async () => {
      generateButton.disabled = true;
      try {
        await api.post(`/api/categories/${categoryId}/notes/generate`, {});
        toast('Dopuna je napisana', 'good');
        notes(root, categoryId);
      } catch (error) {
        toast(error.message, 'bad');
        generateButton.disabled = false;
      }
    },
  });

  const addButton = el('button', {
    class: 'btn', text: '+ Moja beleška',
    onClick: () => {
      const title = el('input', { type: 'text', placeholder: 'Naslov' });
      const body = el('textarea', { rows: 8, placeholder: 'Tekst beleške (markdown radi)...' });
      modal({
        title: 'Nova beleška',
        body: el('div', {}, [field('Naslov', title), field('Tekst', body)]),
        onConfirm: async () => {
          await api.post(`/api/categories/${categoryId}/notes`,
                         { title: title.value, body: body.value });
          notes(root, categoryId);
        },
      });
    },
  });

  mount(root,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__body' }, [
        el('div', { class: 'small muted mb1',
                    text: 'Dopune su dodatni sloj koji čitaš — tvoji originalni materijali se ne diraju.' }),
        el('div', { class: 'btn-row' }, [generateButton, addButton]),
      ]),
    ]),

    rows.length
      ? el('div', {}, rows.map((note) =>
          el('div', { class: 'card' }, [
            el('div', { class: 'card__head' }, [
              note.title,
              el('small', { text: `${note.author === 'ai' ? 'AI' : 'ti'} · ${when(note.created_at)}` }),
              el('div', { class: 'grow' }),
              el('button', {
                class: 'btn btn--sm btn--ghost', text: '🗑',
                onClick: async () => {
                  if (!await confirmDialog('Obrisati belešku?', note.title)) return;
                  await api.del(`/api/notes/${note.id}`);
                  notes(root, categoryId);
                },
              }),
            ]),
            el('div', { class: 'card__body prose', html: markdown(note.body) }),
          ])))
      : el('div', { class: 'empty' }, [
          el('div', { class: 'empty__title', text: 'Još nema dopuna' }),
          el('div', { text: 'Uradi nekoliko sesija — kad se vide rupe, AI zna šta da dopiše.' }),
        ]),
  );
}

function debounce(handler, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => handler(...args), delay);
  };
}
