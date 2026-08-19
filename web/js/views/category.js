// Ekrani unutar predmeta: pregled, materijali, generisanje pitanja.

import { api, followJob } from '../api.js';
import { el, mount, modal, field, toast, bytes, when, confirmDialog } from '../dom.js';
import { store, reloadTree, typeLabel, modelFor } from '../store.js';

const RUN_KIND = {
  manual_import: 'ručni uvoz',
  exam_local: 'ispitna baza, doslovno',
  exam_ai: 'ispitna baza, AI prepis',
};

// ---------------------------------------------------------------- pregled

export async function overview(root, categoryId, go) {
  mount(root, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Učitavam...']));

  const [detail, stats, questions] = await Promise.all([
    api.get(`/api/categories/${categoryId}`),
    api.get(`/api/categories/${categoryId}/stats`),
    api.get(`/api/categories/${categoryId}/questions?limit=1`),
  ]);

  const promptInput = el('textarea', {
    rows: 5,
    text: detail.category.study_prompt || '',
    placeholder: 'Npr. "Uči se samo do lekcije 5. Preskoči dokaze teorema. Oznake koristi kao u skripti."',
  });

  const totals = stats.stats;
  const typeRows = Object.entries(questions.type_counts || {})
    .sort((a, b) => b[1] - a[1]);

  mount(root,
    el('div', { class: 'grid mb2' }, [
      tile(totals.total, 'pitanja'),
      tile(totals.due, 'na redu sada', 'due'),
      tile(totals.weak, 'slabe tačke', 'weak'),
      tile(totals.mastered, 'savladano', 'mastered'),
    ]),

    el('div', { class: 'btn-row mb2' }, [
      el('button', { class: 'btn btn--primary', text: '▶ Uči', onClick: () => go('uci'),
                     disabled: totals.total === 0 }),
      el('button', { class: 'btn', text: '+ Materijali', onClick: () => go('materijali') }),
      el('button', { class: 'btn', text: '✨ Generiši pitanja', onClick: () => go('generisanje') }),
    ]),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, [
        'Šta se tačno uči',
        el('small', { text: 'ovo uputstvo ide u svaki prompt' }),
      ]),
      el('div', { class: 'card__body' }, [
        promptInput,
        el('div', { class: 'field__hint',
                    text: 'Uputstvo roditeljske kategorije se automatski dodaje ispred ovoga.' }),
        detail.breadcrumb.length > 1
          ? el('div', { class: 'mt1' }, [
              el('div', { class: 'field__label', text: 'Ukupno uputstvo koje model dobija' }),
              el('pre', { class: 'mono tiny',
                          style: { whiteSpace: 'pre-wrap', background: 'var(--bg)',
                                   padding: '10px', borderRadius: '7px', margin: '0' },
                          text: detail.effective_prompt || '(prazno)' }),
            ])
          : null,
        el('div', { class: 'btn-row mt2' }, [
          el('button', {
            class: 'btn btn--primary', text: 'Sačuvaj uputstvo',
            onClick: async (event) => {
              event.currentTarget.disabled = true;
              await api.patch(`/api/categories/${categoryId}`, { study_prompt: promptInput.value });
              toast('Sačuvano', 'good');
              overview(root, categoryId, go);
            },
          }),
        ]),
      ]),
    ]),

    typeRows.length
      ? el('div', { class: 'card' }, [
          el('div', { class: 'card__head' }, ['Pitanja po tipu']),
          el('div', { class: 'list' }, typeRows.map(([key, count]) =>
            el('div', { class: 'list__row' }, [
              el('div', { class: 'list__main', text: typeLabel(key) }),
              el('span', { class: 'badge', text: String(count) }),
            ]))),
        ])
      : null,

    stats.activity.length
      ? el('div', { class: 'card' }, [
          el('div', { class: 'card__head' }, ['Aktivnost poslednjih 30 dana']),
          el('div', { class: 'card__body' }, [activityChart(stats.activity)]),
        ])
      : null,
  );
}

export function tile(value, label, kind = '') {
  return el('div', { class: `stat ${kind ? 'stat--' + kind : ''}` }, [
    el('div', { class: 'stat__value', text: String(value ?? 0) }),
    el('div', { class: 'stat__label', text: label }),
  ]);
}

function activityChart(rows) {
  const max = Math.max(...rows.map((row) => row.asked), 1);
  return el('div', { class: 'scroll-x' }, [
    el('div', { style: { display: 'flex', alignItems: 'flex-end', gap: '4px', height: '110px', minWidth: '100%' } },
      rows.map((row) => {
        const share = row.asked ? row.correct / row.asked : 0;
        return el('div', {
          title: `${row.day}: ${row.correct}/${row.asked} tačno`,
          style: {
            flex: '1', minWidth: '9px', height: `${(row.asked / max) * 100}%`,
            background: share >= 0.8 ? 'var(--good)' : (share >= 0.5 ? 'var(--warn)' : 'var(--bad)'),
            borderRadius: '3px 3px 0 0', opacity: '0.85',
          },
        });
      })),
  ]);
}

// ---------------------------------------------------------------- materijali

export async function materials(root, categoryId) {
  const listBox = el('div');
  const jobBox = el('div');

  const picker = el('input', {
    type: 'file', multiple: true, class: 'hidden',
    onChange: (event) => send([...event.target.files]),
  });

  const zone = el('div', { class: 'dropzone', onClick: () => picker.click() }, [
    el('div', { style: { fontSize: '28px' }, text: '📎' }),
    el('div', { class: 'mt1', text: 'Prevuci fajlove ovde ili klikni da izabereš' }),
    el('div', { class: 'tiny faint mt1',
                text: 'PDF, Word, Excel, PowerPoint, slike, snimci, tekst, titlovi' }),
  ]);

  for (const eventName of ['dragenter', 'dragover']) {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add('is-over');
    });
  }
  for (const eventName of ['dragleave', 'drop']) {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.remove('is-over');
    });
  }
  zone.addEventListener('drop', (event) => send([...event.dataTransfer.files]));

  async function send(files) {
    if (!files.length) return;
    mount(jobBox, el('div', { class: 'job' }, [
      el('div', { class: 'spinner' }), `Šaljem ${files.length} fajl(ova)...`,
    ]));

    let response;
    try {
      response = await api.upload(`/api/categories/${categoryId}/materials`, files);
    } catch (error) {
      mount(jobBox);
      toast(error.message, 'bad');
      return;
    }

    for (const failure of response.failures || []) {
      toast(`${failure.filename}: ${failure.error}`, 'bad');
    }
    if (response.duplicates?.length) {
      toast(`${response.duplicates.length} fajl(ova) je već ovde — preskočeno.`);
    }

    if (response.job) {
      const bar = el('span', { style: { width: '0%' } });
      const label = el('div', { class: 'grow', text: 'Čitam fajlove...' });
      mount(jobBox, el('div', { class: 'job' }, [
        el('div', { class: 'spinner' }), label, el('div', { class: 'job__bar' }, [bar]),
      ]));

      await followJob(response.job.id, (job) => {
        label.textContent = job.message || 'Obrada...';
        bar.style.width = job.total ? `${(job.done / job.total) * 100}%` : '0%';
      });
      toast('Fajlovi su obrađeni', 'good');
    }

    mount(jobBox);
    reloadTree();
    draw();
  }

  async function draw() {
    const { materials: rows } = await api.get(`/api/categories/${categoryId}/materials`);
    if (!rows.length) {
      mount(listBox, el('div', { class: 'empty' }, [
        el('div', { class: 'empty__title', text: 'Još nema materijala' }),
        el('div', { text: 'Ubaci skriptu, slajdove, slike table ili snimak predavanja.' }),
      ]));
      return;
    }

    mount(listBox, el('div', { class: 'list' }, rows.map((row) =>
      el('div', { class: 'list__row' }, [
        el('div', { style: { fontSize: '20px' }, text: kindIcon(row.kind) }),
        el('div', { class: 'list__main' }, [
          el('div', { class: 'list__title', text: row.filename }),
          el('div', { class: 'list__meta',
                      text: `${bytes(row.size_bytes)} · ${statusLabel(row)} · ${when(row.created_at)}` }),
        ]),
        row.include_in_study ? null : el('span', { class: 'badge', text: 'isključen' }),
        el('span', { class: `badge ${statusKind(row.extraction_status)}`,
                     text: row.extraction_status === 'local_ok'
                       ? `${row.char_count.toLocaleString('sr-RS')} znakova`
                       : shortStatus(row.extraction_status) }),
        el('button', { class: 'btn btn--sm btn--ghost', text: '👁', title: 'Pogledaj šta je pročitano',
                       onClick: () => showPreview(row.id) }),
        el('button', { class: 'btn btn--sm btn--ghost', text: '⟳', title: 'Pročitaj ponovo',
                       onClick: async (event) => {
                         event.currentTarget.disabled = true;
                         await api.post(`/api/materials/${row.id}/reprocess`);
                         toast('Ponovo pročitano', 'good');
                         draw();
                       } }),
        el('button', { class: 'btn btn--sm btn--ghost', text: '🗑', title: 'Obriši',
                       onClick: async () => {
                         if (!await confirmDialog('Obrisati materijal?',
                             `${row.filename} se briše sa diska. Pitanja koja su iz njega već napravljena ostaju.`)) return;
                         await api.del(`/api/materials/${row.id}`);
                         toast('Obrisano');
                         reloadTree();
                         draw();
                       } }),
      ]))));
  }

  async function showPreview(materialId) {
    const payload = await api.get(`/api/materials/${materialId}`);
    const material = payload.material;
    modal({
      wide: true,
      title: material.filename,
      body: el('div', {}, [
        el('div', { class: 'small muted mb1',
                    text: `${statusLabel(material)}${material.page_count ? ` · ${material.page_count} strana` : ''}` }),
        material.extraction_note ? el('div', { class: 'tiny faint mb1', text: material.extraction_note }) : null,
        payload.outline.length
          ? el('div', { class: 'mb2' }, [
              el('div', { class: 'field__label', text: 'Nađeni naslovi' }),
              el('div', { class: 'btn-row' }, payload.outline.slice(0, 30).map((item) =>
                el('span', { class: 'badge', text: item }))),
            ])
          : null,
        el('div', { class: 'field__label', text: 'Pročitan tekst (početak)' }),
        el('pre', { class: 'mono tiny',
                    style: { whiteSpace: 'pre-wrap', maxHeight: '46vh', overflow: 'auto',
                             background: 'var(--bg)', padding: '12px', borderRadius: '7px' },
                    text: payload.preview || '(ništa nije pročitano lokalno — original ide AI-u)' }),
      ]),
    });
  }

  mount(root, el('div', { class: 'mb2' }, [zone, picker]), jobBox, listBox);
  draw();
}

function kindIcon(kind) {
  return { pdf: '📕', document: '📘', image: '🖼', audio: '🎧', video: '🎬', text: '📄' }[kind] || '📎';
}

function statusKind(status) {
  return { local_ok: 'badge--good', remote_needed: 'badge--warn', failed: 'badge--bad' }[status] || '';
}

function shortStatus(status) {
  return { remote_needed: 'ide AI-u', pending: 'čeka', failed: 'greška', local_poor: 'slab tekst' }[status] || status;
}

function statusLabel(row) {
  if (row.extraction_status === 'local_ok') return `pročitano lokalno (${row.extraction_method})`;
  if (row.extraction_status === 'remote_needed') return 'čita AI iz originala';
  if (row.extraction_status === 'failed') return 'čitanje nije uspelo';
  return 'čeka obradu';
}


// Rezime uvoza pitanja - isti za generisanje, rucni uvoz i ispitnu bazu.
export function showImportResult(result, { title = 'Generisanje završeno', extraTiles = [], skipped = [] } = {}) {
  modal({
    title,
    body: el('div', {}, [
      el('div', { class: 'grid mb2' }, [
        tile(result.inserted || 0, 'novih pitanja', 'mastered'),
        tile(result.duplicates || 0, 'duplikata'),
        tile((result.rejected || []).length, 'odbijeno', 'weak'),
        ...(extraTiles.length ? extraTiles.map(([value, label, kind]) => tile(value, label, kind))
                              : [tile(result.calls || 0, 'poziva')]),
      ]),
      (result.errors || []).length
        ? el('div', { class: 'card' }, [
            el('div', { class: 'card__head' }, ['Napomene']),
            el('div', { class: 'card__body small' }, (result.errors || []).map((item) =>
              el('div', { class: 'mb1', text: '• ' + item }))),
          ])
        : null,
      skipped.length
        ? el('div', { class: 'card' }, [
            el('div', { class: 'card__head' }, ['Preskočena pitanja i zašto']),
            el('div', { class: 'list' }, skipped.slice(0, 30).map((item) =>
              el('div', { class: 'list__row' }, [
                el('div', { class: 'list__main' }, [
                  el('div', { class: 'list__title', text: `${item.number ? item.number + '. ' : ''}${item.stem || '(bez teksta)'}` }),
                  el('div', { class: 'list__meta', text: item.reason }),
                ]),
              ]))),
          ])
        : null,
      (result.rejected || []).length
        ? el('div', { class: 'card' }, [
            el('div', { class: 'card__head' }, ['Odbijena pitanja i zašto']),
            el('div', { class: 'list' }, (result.rejected || []).slice(0, 30).map((item) =>
              el('div', { class: 'list__row' }, [
                el('div', { class: 'list__main' }, [
                  el('div', { class: 'list__title', text: item.stem || '(bez teksta)' }),
                  el('div', { class: 'list__meta', text: item.reason }),
                ]),
              ]))),
          ])
        : null,
    ]),
  });
}

// ---------------------------------------------------------------- generisanje

export async function generate(root, categoryId) {
  const options = {
    include_subtree: true,
    count_per_call: 25,
    variants: store.settings.generate_variants ?? 2,
    tier: 'standard',
    max_calls: 0,
    include_files: true,
    extra_instructions: '',
  };

  const planBox = el('div', { class: 'mb2' });
  const jobBox = el('div');
  const runsBox = el('div');

  async function refreshPlan() {
    mount(planBox, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Računam obim...']));
    try {
      const { plan } = await api.post(`/api/categories/${categoryId}/generate/plan`, options);
      mount(planBox, el('div', { class: 'card' }, [
        el('div', { class: 'card__head' }, ['Šta će biti poslato', el('small', { text: plan.model })]),
        el('div', { class: 'card__body' }, [
          el('div', { class: 'grid' }, [
            tile(plan.total_calls, 'poziva modelu'),
            tile(plan.total_chars.toLocaleString('sr-RS'), 'znakova gradiva'),
            tile(`~${Math.round(plan.approx_tokens / 1000)}k`, 'procena tokena'),
            tile(`~${plan.questions_expected}`, 'očekivano pitanja'),
          ]),
          plan.remote_files.length
            ? el('div', { class: 'mt2' }, [
                el('div', { class: 'field__label',
                            text: `Originali koji idu AI-u (${plan.remote_files.length})` }),
                el('div', { class: 'btn-row' }, plan.remote_files.map((file) =>
                  el('span', { class: 'badge badge--warn', title: file.reason, text: file.filename }))),
              ])
            : null,
          plan.total_calls === 0
            ? el('div', { class: 'mt1 muted',
                          text: 'Nema materijala. Prvo ubaci fajlove u tab Materijali.' })
            : null,
        ]),
      ]));
    } catch (error) {
      mount(planBox, el('div', { class: 'card' }, [
        el('div', { class: 'card__body muted', text: error.message }),
      ]));
    }
  }

  const numberInput = (key, label, min, max) => field(label, el('input', {
    type: 'number', min: String(min), max: String(max), value: String(options[key]),
    onInput: (event) => { options[key] = Number(event.target.value); refreshPlan(); },
  }));

  async function run() {
    if (!store.settings.gemini_api_key_set) {
      toast('Prvo unesi Gemini API ključ u Podešavanjima.', 'bad');
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
      const response = await api.post(`/api/categories/${categoryId}/generate`, options);
      job = response.job;
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
    if (finished.status === 'failed') { toast(finished.error || 'Generisanje nije uspelo.', 'bad'); }
    else showImportResult(finished.result || {});
    reloadTree();
    loadRuns();
  }

  async function openExport() {
    let payload;
    try {
      payload = await api.post(`/api/categories/${categoryId}/generate/export`, options);
    } catch (error) {
      toast(error.message, 'bad');
      return;
    }

    const area = el('textarea', { class: 'mono', rows: 14, text: payload.text, readonly: true });
    modal({
      wide: true,
      title: `Prompt za drugi model (deo ${payload.batch_index + 1} od ${payload.batch_count})`,
      body: el('div', {}, [
        el('div', { class: 'small muted mb1',
                    text: `${payload.chars.toLocaleString('sr-RS')} znakova · izvori: ${payload.sources.join(', ')}` }),
        area,
        el('div', { class: 'btn-row mt1' }, [
          el('button', {
            class: 'btn btn--primary', text: '📋 Kopiraj sve',
            onClick: async () => {
              await navigator.clipboard.writeText(payload.text);
              toast('Kopirano — nalepi u Claude', 'good');
            },
          }),
          payload.batch_count > 1
            ? el('button', {
                class: 'btn', text: 'Sledeći deo →',
                onClick: () => {
                  options.batch_index = (payload.batch_index + 1) % payload.batch_count;
                  openExport();
                },
              })
            : null,
        ]),
      ]),
    });
  }

  function openImport() {
    const area = el('textarea', { class: 'mono', rows: 12,
                                  placeholder: 'Nalepi ovde ceo odgovor drugog modela...' });
    modal({
      wide: true,
      title: 'Nalepi odgovor iz drugog modela',
      confirmText: 'Uvezi',
      body: el('div', {}, [
        el('div', { class: 'small muted mb1',
                    text: 'Prolazi kroz istu proveru kao Gemini-jev odgovor. Neispravna pitanja se odbijaju sa razlogom, ispravna se upisuju.' }),
        area,
      ]),
      onConfirm: async () => {
        try {
          const result = await api.post(`/api/categories/${categoryId}/generate/import`,
                                        { text: area.value });
          toast(`Uvezeno ${result.inserted}, duplikata ${result.duplicates}, odbijeno ${result.rejected.length}`,
                result.inserted ? 'good' : 'bad');
          if (result.rejected.length) showImportResult({ ...result, rejected: result.rejected });
          reloadTree();
          loadRuns();
        } catch (error) {
          toast(error.message, 'bad');
          return false;
        }
      },
    });
  }

  async function loadRuns() {
    const { runs } = await api.get(`/api/categories/${categoryId}/runs`);
    if (!runs.length) { mount(runsBox); return; }
    mount(runsBox, el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Istorija generisanja']),
      el('div', { class: 'list' }, runs.slice(0, 15).map((run) =>
        el('div', { class: 'list__row' }, [
          el('div', { class: 'list__main' }, [
            el('div', { class: 'list__title', text: `${run.model} · ${RUN_KIND[run.source_kind] || 'automatski'}` }),
            el('div', { class: 'list__meta',
                        text: `${when(run.created_at)}${run.error ? ' · ' + run.error : ''}` }),
          ]),
          el('span', { class: 'badge badge--good', text: `+${run.produced_count}` }),
          run.duplicate_count ? el('span', { class: 'badge', text: `${run.duplicate_count} dupl.` }) : null,
          run.rejected_count ? el('span', { class: 'badge badge--warn', text: `${run.rejected_count} odb.` }) : null,
          el('span', { class: `badge ${run.status === 'done' ? 'badge--good' : 'badge--bad'}`, text: run.status }),
        ]))),
    ]));
  }

  mount(root,
    planBox,
    jobBox,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Podešavanja generisanja']),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'row2' }, [
          numberInput('count_per_call', 'Pitanja po pozivu', 5, 80),
          numberInput('variants', 'Varijacija po pitanju', 0, 4),
        ]),
        el('div', { class: 'row2' }, [
          field('Model', el('select', {
            onChange: (event) => { options.tier = event.target.value; refreshPlan(); },
          }, [
            el('option', { value: 'fast', text: `Brz i jeftin (${modelFor('fast')})` }),
            el('option', { value: 'standard', selected: true, text: `Standardni (${modelFor('standard')})` }),
            el('option', { value: 'strong', text: `Najjači (${modelFor('strong')})` }),
          ]), 'Jači model daje bolja pitanja ali brže troši besplatnu kvotu.'),
          numberInput('max_calls', 'Najviše poziva (0 = bez granice)', 0, 50),
        ]),
        field('Dodatno uputstvo modelu (opciono)', el('textarea', {
          rows: 2,
          placeholder: 'Npr. "Više računskih zadataka, manje definicija."',
          onInput: (event) => { options.extra_instructions = event.target.value; },
        })),
        el('label', { class: 'checkline' }, [
          el('input', { type: 'checkbox', checked: true,
                        onChange: (event) => { options.include_subtree = event.target.checked; refreshPlan(); } }),
          'Koristi i materijale iz podkategorija',
        ]),
        el('label', { class: 'checkline' }, [
          el('input', { type: 'checkbox', checked: true,
                        onChange: (event) => { options.include_files = event.target.checked; refreshPlan(); } }),
          'Pošalji i originalne fajlove koje lokalno nismo pročitali (slike, skenovi, snimci)',
        ]),
        el('div', { class: 'btn-row mt2' }, [
          el('button', { class: 'btn btn--primary', text: '✨ Generiši preko Gemini-ja', onClick: run }),
          el('button', { class: 'btn', text: '📤 Izvezi prompt za Claude', onClick: openExport }),
          el('button', { class: 'btn', text: '📥 Nalepi odgovor', onClick: openImport }),
        ]),
      ]),
    ]),
    runsBox,
  );

  refreshPlan();
  loadRuns();
}
