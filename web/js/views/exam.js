// Ispitna baza: fiksna lista pitanja sa fakulteta ulazi u aplikaciju DOSLOVNO.
//
// Za razliku od taba "Generisanje", ovde AI nista ne pise: parser cita
// dokument i prepisuje pitanje i odgovore znak po znak. AI je samo rezervni
// rezim za nesredjene fajlove i skenove, i tada se svako pitanje proverava da
// li stvarno postoji u tekstu.

import { api, followJob } from '../api.js';
import { el, mount, modal, field, toast } from '../dom.js';
import { store, reloadTree, modelFor, typeLabel } from '../store.js';
import { showImportResult, tile } from './category.js';

const FORMAT_EXAMPLE = `1. Koji dokument propisuje sadržaj obuke?
a) Plan obuke
b) Program obuke *
c) Plan časa

2. Obuka traje tri meseca.
a) Tačno
b) Netačno
Tačan odgovor: b

3. Ko donosi program obuke?
Odgovor: ministar

Odgovori:
1. b
2. b`;

export async function examBank(root, categoryId) {
  const state = {
    material_ids: [],
    text: '',
    keep_order: true,
    strict: true,
    tier: 'standard',
  };

  const sourceBox = el('div');
  const previewBox = el('div');
  const jobBox = el('div');

  const { materials } = await api.get(`/api/categories/${categoryId}/materials?subtree=1`);
  const usable = materials.filter((row) => row.include_in_study);

  const textArea = el('textarea', {
    rows: 8, class: 'mono',
    placeholder: 'Ili nalepi ovde tekst sa pitanjima (kopiran iz Worda, PDF-a, mejla...)',
    onInput: (event) => { state.text = event.target.value; },
  });

  function drawSources() {
    mount(sourceBox,
      usable.length
        ? el('div', { class: 'list' }, usable.map((row) =>
            el('label', { class: 'list__row', style: { cursor: 'pointer' } }, [
              el('input', {
                type: 'checkbox',
                onChange: (event) => {
                  if (event.target.checked) state.material_ids.push(row.id);
                  else state.material_ids = state.material_ids.filter((id) => id !== row.id);
                },
              }),
              el('div', { class: 'list__main' }, [
                el('div', { class: 'list__title', text: row.filename }),
                el('div', { class: 'list__meta',
                            text: row.extraction_status === 'local_ok'
                              ? `${row.char_count.toLocaleString('sr-RS')} znakova pročitano lokalno`
                              : 'nema lokalnog teksta — može samo preko AI prepisa' }),
              ]),
              row.extraction_status === 'local_ok'
                ? el('span', { class: 'badge badge--good', text: 'tekst' })
                : el('span', { class: 'badge badge--warn', text: 'sken/slika' }),
            ])))
        : el('div', { class: 'muted small mb1',
                      text: 'U ovoj kategoriji još nema materijala. Ubaci fajl sa pitanjima u tab Materijali, ili nalepi tekst ispod.' }),
      el('div', { class: 'mt1' }, [textArea]),
    );
  }

  async function recognise() {
    mount(previewBox, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Čitam pitanja...']));
    let preview;
    try {
      preview = await api.post(`/api/categories/${categoryId}/exam/preview`, state);
    } catch (error) {
      mount(previewBox);
      toast(error.message, 'bad');
      return;
    }
    drawPreview(preview);
  }

  function drawPreview(preview) {
    const stats = preview.stats;
    const localButton = el('button', {
      class: `btn ${preview.recommendation === 'local' ? 'btn--primary' : ''}`,
      text: `📥 Uvezi doslovno, bez AI (${preview.importable})`,
      disabled: preview.importable === 0,
      onClick: () => runLocal(),
    });
    const aiButton = el('button', {
      class: `btn ${preview.recommendation === 'ai' ? 'btn--primary' : ''}`,
      text: '🤖 AI prepiše doslovno (Gemini)',
      onClick: () => runAi(),
    });

    mount(previewBox,
      el('div', { class: 'card' }, [
        el('div', { class: 'card__head' }, ['Šta je prepoznato', el('small', { text: 'ništa još nije upisano' })]),
        el('div', { class: 'card__body' }, [
          el('div', { class: 'grid mb2' }, [
            tile(stats.total, 'pitanja nađeno'),
            tile(stats.with_answer, 'sa tačnim odgovorom', 'mastered'),
            tile(stats.without_answer, 'bez odgovora', stats.without_answer ? 'weak' : ''),
            tile(preview.remote_files.length, 'fajlova bez teksta (sken)'),
          ]),
          preview.recommendation === 'ai' && stats.total === 0
            ? el('div', { class: 'small muted mb1',
                          text: 'Parser nije prepoznao numerisana pitanja. Ili dokument nije u tom formatu (vidi „Koji format se prepoznaje"), ili je sken — tada AI prepis.' })
            : null,
          stats.without_answer
            ? el('div', { class: 'small muted mb1',
                          text: `${stats.without_answer} pitanja nema označen tačan odgovor — bez AI se preskaču. AI prepis ih uveze i označi 🔍 „provera u fajlu" da znaš da je odgovor odredio model, ne dokument.` })
            : null,
          stats.warnings.length
            ? el('div', { class: 'small mb1' }, stats.warnings.slice(0, 10).map((line) =>
                el('div', { class: 'tiny faint', text: '• ' + line })))
            : null,
          el('div', { class: 'btn-row mt1' }, [localButton, aiButton]),
        ]),
      ]),
      preview.questions.length
        ? el('div', { class: 'card' }, [
            el('div', { class: 'card__head' }, [
              `Pitanja kako će ući u bazu (${preview.shown}${preview.shown < stats.total ? ' od ' + stats.total : ''})`,
            ]),
            el('div', { class: 'list' }, preview.questions.map((item) =>
              el('div', { class: 'list__row' }, [
                el('div', { class: 'list__main' }, [
                  el('div', { class: 'list__title', text: `${item.number ? item.number + '. ' : ''}${item.stem}` }),
                  item.skipped
                    ? el('div', { class: 'list__meta', style: { color: 'var(--bad)' }, text: `preskače se: ${item.skipped}` })
                    : el('div', { class: 'list__meta',
                                  text: `${typeLabel(item.type)}` +
                                        (item.options.length ? ` · ${item.options.length} odgovora` : '') +
                                        (item.correct ? ` · tačno: ${item.correct}` : '') }),
                ]),
                item.skipped
                  ? el('span', { class: 'badge badge--warn', text: 'preskočeno' })
                  : el('span', { class: 'badge badge--good', text: '1:1' }),
              ]))),
          ])
        : null,
    );
  }

  async function runLocal() {
    let result;
    try {
      result = await api.post(`/api/categories/${categoryId}/exam/import`, { ...state, mode: 'local' });
    } catch (error) {
      toast(error.message, 'bad');
      return;
    }
    finish(result);
  }

  async function runAi() {
    if (!store.settings.gemini_api_key_set) {
      toast('Za AI prepis prvo unesi Gemini API ključ u Podešavanjima. Uvoz bez AI radi i bez ključa.', 'bad');
      return;
    }
    const bar = el('span', { style: { width: '0%' } });
    const label = el('div', { class: 'grow', text: 'Pokrećem...' });
    const cancelButton = el('button', { class: 'btn btn--sm', text: 'Prekini' });
    mount(jobBox, el('div', { class: 'job' }, [
      el('div', { class: 'spinner' }), label, el('div', { class: 'job__bar' }, [bar]), cancelButton,
    ]));

    let job;
    try {
      ({ job } = await api.post(`/api/categories/${categoryId}/exam/import`, { ...state, mode: 'ai' }));
    } catch (error) {
      mount(jobBox);
      toast(error.message, 'bad');
      return;
    }
    cancelButton.onclick = () => api.post(`/api/jobs/${job.id}/cancel`);
    const finished = await followJob(job.id, (tick) => {
      label.textContent = tick.message || 'Radim...';
      bar.style.width = tick.total ? `${(tick.done / tick.total) * 100}%` : '0%';
    });
    mount(jobBox);
    if (finished.status === 'failed') toast(finished.error || 'Prepis nije uspeo.', 'bad');
    else finish(finished.result || {});
  }

  function finish(result) {
    showImportResult(result, {
      title: 'Uvoz ispitnih pitanja završen',
      extraTiles: result.flagged ? [[result.flagged, '🔍 za proveru', 'weak']] : [],
      skipped: result.skipped || [],
    });
    toast(result.inserted ? `Uvezeno ${result.inserted} pitanja, doslovno.` : 'Ništa nije uvezeno.',
          result.inserted ? 'good' : 'bad');
    reloadTree();
    mount(previewBox);
  }

  function showFormatHelp() {
    modal({
      wide: true,
      title: 'Koji format se prepoznaje (bez AI)',
      body: el('div', {}, [
        el('div', { class: 'small mb1', text: 'Pitanja numerisana (1. / 1) / Pitanje 1), ponuđeni odgovori sa a) b) c) ili crticom, tačan odgovor označen na bilo koji od ovih načina:' }),
        el('ul', { class: 'small mb1' }, [
          el('li', { text: 'zvezdica ili + ispred ili iza tačnog odgovora: "*b) ministar" ili "b) ministar *"' }),
          el('li', { text: '"Tačan odgovor: b" (ili "Odgovor: b", "Rešenje: b") ispod ponuđenih' }),
          el('li', { text: 'ključ na kraju dokumenta: red "Odgovori:" pa "1. b", "2) c", "6. a, c"' }),
          el('li', { text: 'otvoreno pitanje: "Odgovor: tekst" ispod pitanja → kratak odgovor' }),
          el('li', { text: 'dve opcije tačno/netačno ili da/ne → tačno/netačno' }),
        ]),
        el('div', { class: 'small mb1', text: 'Word i PDF ne čuvaju podebljano slovo kad se čitaju kao tekst — ako je tačan odgovor označen SAMO boldom, dodaj zvezdicu ili ključ na kraju, ili pusti AI prepis.' }),
        el('pre', { class: 'mono tiny',
                    style: { whiteSpace: 'pre-wrap', background: 'var(--bg)', padding: '12px', borderRadius: '7px' },
                    text: FORMAT_EXAMPLE }),
      ]),
    });
  }

  mount(root,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Ispitna baza — pitanja tačno kako pišu', el('small', { text: 'bez AI prepravljanja' })]),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'small muted mb2',
                    text: 'Imaš fiksnu listu pitanja koja dolaze na ispit 1:1? Ubaci je ovde. Pitanje i ponuđeni odgovori se upisuju doslovno iz dokumenta — ništa se ne parafrazira, ne dodaje i ne meša. Posle toga u tabu „Uči" možeš da vežbaš samo njih.' }),
        el('div', { class: 'field__label', text: 'Izvor: izaberi fajl(ove) iz materijala' }),
        sourceBox,
        el('div', { class: 'row2 mt2' }, [
          el('div', {}, [
            el('label', { class: 'checkline' }, [
              el('input', { type: 'checkbox', checked: true,
                            onChange: (event) => { state.keep_order = event.target.checked; } }),
              'Zadrži redosled ponuđenih odgovora kao u dokumentu',
            ]),
            el('div', { class: 'field__hint', text: 'Isključi ako hoćeš da se odgovori mešaju pri svakom prikazu (teže za „pamćenje slova").' }),
            el('label', { class: 'checkline mt1' }, [
              el('input', { type: 'checkbox', checked: true,
                            onChange: (event) => { state.strict = event.target.checked; } }),
              'AI prepis: odbaci sve što nije nađeno doslovno u tekstu fajla',
            ]),
          ]),
          field('Model za AI prepis (samo ako zatreba)', el('select', {
            onChange: (event) => { state.tier = event.target.value; },
          }, [
            el('option', { value: 'fast', text: `Brz (${modelFor('fast')})` }),
            el('option', { value: 'standard', selected: true, text: `Standardni (${modelFor('standard')})` }),
            el('option', { value: 'strong', text: `Najjači (${modelFor('strong')})` }),
          ]), 'Za skenove i slike uzmi jači model — čita rukopis i loš sken bolje.'),
        ]),
        el('div', { class: 'btn-row mt2' }, [
          el('button', { class: 'btn btn--primary', text: '🔎 Prepoznaj pitanja', onClick: recognise }),
          el('button', { class: 'btn btn--ghost', text: 'Koji format se prepoznaje?', onClick: showFormatHelp }),
        ]),
      ]),
    ]),
    jobBox,
    previewBox,
  );

  drawSources();
}

