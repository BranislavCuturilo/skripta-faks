// Ekran ucenja: podesavanje sesije, petlja pitanja, rezime.

import { api } from '../api.js';
import { el, mount, modal, field, toast, percent, markdown } from '../dom.js';
import { store, typeLabel, reloadTree } from '../store.js';
import { renderQuestion } from '../render.js';
import * as tts from '../tts.js';

const AGGRESSIVENESS_LABELS = {
  1: 'Opušteno — može po nešto i da ne znam',
  2: 'Blago',
  3: 'Uravnoteženo',
  4: 'Strogo',
  5: 'Moram sve da znam',
};

const MODES = [
  ['adaptive', 'Pametno (preporuka)', 'Forsira ono što grešiš, savladano provlači povremeno.'],
  ['weak', 'Samo slabe tačke', 'Od najslabijeg naviše.'],
  ['new', 'Samo novo', 'Pitanja koja još nisi video.'],
  ['flagged', 'Označena za proveru', 'Ono što si sam obeležio.'],
  ['all', 'Sve nasumično', 'Bez ikakvog reda.'],
];

export function studySetup(root, categoryId, onStarted) {
  const stats = { total: 0 };
  const state = {
    mode: 'adaptive',
    length: store.settings.session_length || 20,
    aggressiveness: store.settings.aggressiveness || 3,
    include_subtree: true,
    type_filter: [],
    origin_filter: '',
  };

  const summary = el('div', { class: 'grid mb2' });
  const typeBox = el('div', { class: 'btn-row' });
  // Prikazuje se samo kad kategorija ima doslovno uvezena ispitna pitanja.
  const originBox = el('div');

  const aggressivenessValue = el('div', { class: 'small muted mb1',
                                          text: AGGRESSIVENESS_LABELS[state.aggressiveness] });
  const slider = el('input', {
    type: 'range', min: '1', max: '5', step: '1', value: String(state.aggressiveness),
    onInput: (event) => {
      state.aggressiveness = Number(event.target.value);
      aggressivenessValue.textContent = AGGRESSIVENESS_LABELS[state.aggressiveness];
      refreshStats();
    },
  });

  const startButton = el('button', {
    class: 'btn btn--primary', text: 'Počni sesiju',
    onClick: async () => {
      startButton.disabled = true;
      try {
        const payload = await api.post('/api/study/start', { category_id: categoryId, ...state });
        onStarted(payload.session.id);
      } catch (error) {
        toast(error.message, 'bad');
        startButton.disabled = false;
      }
    },
  });

  async function refreshStats() {
    const payload = await api.get(
      `/api/categories/${categoryId}/stats?subtree=${state.include_subtree ? 1 : 0}` +
      `&aggressiveness=${state.aggressiveness}`
    );
    Object.assign(stats, payload.stats);
    mount(summary,
      statTile(stats.total, 'ukupno pitanja'),
      statTile(stats.due, 'na redu sada', 'due'),
      statTile(stats.weak, 'slabe tačke', 'weak'),
      statTile(stats.mastered, 'savladano', 'mastered'),
      statTile(stats.unseen, 'još neviđeno'),
    );
    startButton.disabled = stats.total === 0;
  }

  const typeCounts = {};
  api.get(`/api/categories/${categoryId}/questions?limit=1`).then(({ type_counts, origin_counts }) => {
    Object.assign(typeCounts, type_counts);
    const examCount = (origin_counts || {}).exam || 0;
    if (examCount) {
      mount(originBox,
        el('label', { class: 'checkline mt1' }, [
          el('input', {
            type: 'checkbox',
            onChange: (event) => { state.origin_filter = event.target.checked ? 'exam' : ''; },
          }),
          `Samo ispitna pitanja — doslovno iz fajla (${examCount})`,
        ]),
        el('div', { class: 'field__hint', text: 'Pitanja iz taba „Ispitna baza": tačno kako pišu u dokumentu, bez AI varijacija.' }),
      );
    }
    mount(typeBox, ...Object.entries(typeCounts).map(([key, count]) =>
      el('button', {
        class: 'tool',
        text: `${typeLabel(key)} (${count})`,
        onClick: (event) => {
          const button = event.currentTarget;
          const on = button.classList.toggle('is-on');
          if (on) state.type_filter.push(key);
          else state.type_filter = state.type_filter.filter((item) => item !== key);
        },
      })));
  });

  mount(root,
    summary,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Kako da te ispitujem']),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'row2' }, [
          field('Način', el('select', {
            onChange: (event) => { state.mode = event.target.value; },
          }, MODES.map(([value, label]) => el('option', { value, text: label }))),
          MODES[0][2]),
          field('Broj pitanja', el('input', {
            type: 'number', min: '1', max: '200', value: String(state.length),
            onInput: (event) => { state.length = Number(event.target.value) || 20; },
          })),
        ]),
        el('div', { class: 'field__label', text: `Agresivnost` }),
        slider,
        aggressivenessValue,
        el('label', { class: 'checkline' }, [
          el('input', {
            type: 'checkbox', checked: true,
            onChange: (event) => { state.include_subtree = event.target.checked; refreshStats(); },
          }),
          'Uključi i sve podkategorije',
        ]),
        originBox,
        el('div', { class: 'field__label mt1', text: 'Ograniči na tipove (ništa = svi)' }),
        typeBox,
      ]),
    ]),
    el('div', { class: 'btn-row' }, [startButton]),
  );

  refreshStats();
}

function statTile(value, label, kind = '') {
  return el('div', { class: `stat ${kind ? 'stat--' + kind : ''}` }, [
    el('div', { class: 'stat__value', text: String(value ?? 0) }),
    el('div', { class: 'stat__label', text: label }),
  ]);
}

// ---------------------------------------------------------------- petlja

export function runSession(root, sessionId, onFinished) {
  let current = null;
  let renderer = null;
  let startedAt = 0;
  let answered = false;

  const progressBar = el('span', { style: { width: '0%' } });
  const counter = el('div', { class: 'study__counter', text: '' });
  const stage = el('div');

  mount(root, el('div', { class: 'study' }, [
    el('div', { class: 'study__bar' }, [
      el('div', { class: 'study__progress' }, [progressBar]),
      counter,
      el('button', {
        class: 'btn btn--sm btn--ghost', text: 'Prekini',
        onClick: async () => {
          tts.stop();
          const { summary } = await api.post(`/api/study/${sessionId}/end`);
          showSummary(summary);
        },
      }),
    ]),
    stage,
  ]));

  async function next() {
    tts.stop();
    answered = false;
    mount(stage, el('div', { class: 'card' }, [
      el('div', { class: 'card__body flex' }, [el('div', { class: 'spinner' }), 'Biram pitanje...']),
    ]));

    let step;
    try {
      step = await api.get(`/api/study/${sessionId}/next`);
    } catch (error) {
      toast(error.message, 'bad');
      return;
    }

    if (step.done) { showSummary(step.summary); return; }

    current = step.question;
    startedAt = Date.now();
    const total = step.asked + step.remaining;
    progressBar.style.width = `${total ? (step.asked / total) * 100 : 0}%`;
    counter.textContent = `${step.asked + 1} / ${total}`;

    drawQuestion();
  }

  function drawQuestion() {
    renderer = renderQuestion(current);

    const answerButton = el('button', { class: 'btn btn--primary', text: 'Odgovori', onClick: submit });
    const body = el('div', { class: 'question' }, [
      el('div', { class: 'flex-between' }, [
        el('div', { class: 'question__type', text: typeLabel(current.type) }),
        el('button', {
          class: 'tool', title: 'Pročitaj naglas', text: '🔊',
          onClick: () => tts.speak(readable(current, renderer)),
        }),
      ]),
      current.type === 'fill_blank' || current.type === 'cloze_dropdown'
        ? null
        : el('div', { class: 'question__stem', text: current.stem }),
      renderer.node,
      el('div', { class: 'btn-row mt2', id: 'answer-actions' }, [answerButton]),
      toolbar(),
    ]);

    if (renderer.autoSubmitOn) {
      body.addEventListener(renderer.autoSubmitOn, submit);
      answerButton.classList.add('hidden');
    }

    mount(stage, body);
    const firstInput = body.querySelector('input[type="text"], textarea');
    if (firstInput) firstInput.focus();

    body.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !answered) submit();
    });
  }

  function toolbar() {
    const flagButton = (key, label, title) => el('button', {
      class: `tool ${current.flags[key] ? 'is-on' : ''}`,
      title,
      text: label,
      onClick: async (event) => {
        const value = !current.flags[key];
        current.flags[key] = value;
        event.currentTarget.classList.toggle('is-on', value);
        await api.post(`/api/questions/${current.id}/meta`, { [key]: value });
        toast(value ? `Označeno: ${title}` : 'Oznaka uklonjena');
      },
    });

    return el('div', { class: 'tools' }, [
      el('button', { class: `tool ${current.note ? 'is-on' : ''}`, text: '📝 Beleška',
                     title: 'Zapiši belešku uz ovo pitanje', onClick: openNote }),
      flagButton('flag_review', '🚩 Proveriti', 'želim ovo ponovo da pogledam'),
      flagButton('flag_check_source', '🔍 Provera u fajlu', 'proveriti da li se ponavlja ili je greška'),
      flagButton('flag_irrelevant', '🗑 Nebitno', 'nebitno, za uklanjanje'),
      el('button', { class: 'tool', text: '⏭ Preskoči', title: 'Ne sada, ali ostaje u igri',
                     onClick: () => skip('skip') }),
      el('button', { class: 'tool', text: '🚫 Zanemari zauvek', title: 'Nikad me više ne pitaj ovo',
                     onClick: () => skip('ignore_forever') }),
    ]);
  }

  function openNote() {
    const input = el('textarea', { rows: 5, text: current.note || '',
                                   placeholder: 'Npr. proveriti u skripti na strani 40...' });
    modal({
      title: 'Beleška uz pitanje',
      body: el('div', {}, [
        el('div', { class: 'small muted mb1', text: current.stem }),
        input,
        el('div', { class: 'field__hint mt1',
                    text: 'Beleška ostaje uz pitanje i preživljava svaku izmenu pitanja.' }),
      ]),
      onConfirm: async () => {
        await api.post(`/api/questions/${current.id}/meta`, { note: input.value });
        current.note = input.value;
        toast('Beleška sačuvana', 'good');
        drawQuestion();
      },
    });
  }

  async function skip(reason) {
    try {
      await api.post(`/api/study/${sessionId}/skip`, { question_id: current.id, reason });
      if (reason === 'ignore_forever') { toast('Pitanje je zanemareno zauvek.'); reloadTree(); }
      next();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function submit() {
    if (answered) return;
    answered = true;

    const actions = stage.querySelector('#answer-actions');
    mount(actions, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Proveravam...']));

    let result;
    try {
      result = await api.post(`/api/study/${sessionId}/answer`, {
        question_id: current.id,
        answer: renderer.collect(),
        response_ms: Date.now() - startedAt,
      });
    } catch (error) {
      toast(error.message, 'bad');
      answered = false;
      mount(actions, el('button', { class: 'btn btn--primary', text: 'Odgovori', onClick: submit }));
      return;
    }

    renderer.reveal(result);
    stage.querySelector('.tools')?.remove();

    const kind = result.is_correct ? 'good' : (result.score > 0 ? 'partial' : 'bad');
    const verdict = result.is_correct
      ? '✅ Tačno'
      : (result.score > 0 ? `➗ Delimično tačno (${percent(result.score)})` : '❌ Netačno');

    const panel = el('div', { class: `feedback feedback--${kind}` }, [
      el('div', { class: 'feedback__verdict' }, [
        verdict,
        result.graded_by === 'ai' ? el('span', { class: 'badge badge--accent', text: 'ocenio AI' }) : null,
        result.graded_by === 'cache' ? el('span', { class: 'badge', text: 'iz keša' }) : null,
      ]),
      result.feedback ? el('div', { class: 'feedback__body prose',
                                    html: markdown(result.feedback) }) : null,
      !result.is_correct && result.correct_text
        ? el('div', { class: 'feedback__correct' }, [
            el('strong', { text: 'Tačan odgovor: ' }), result.correct_text,
          ])
        : null,
      result.misconception
        ? el('div', { class: 'tiny mt1' }, [
            el('span', { class: 'badge badge--warn', text: 'obrazac greške' }), ' ', result.misconception,
          ])
        : null,
      result.progress && result.progress.due_at
        ? el('div', { class: 'tiny faint mt1',
                      text: `Sledeći put: ${result.progress.interval_days < 1
                        ? 'uskoro' : `za ~${Math.round(result.progress.interval_days)} dana`}` +
                            ` · savladanost ${percent(result.progress.mastery)}` })
        : null,
    ]);

    const continueButton = el('button', { class: 'btn btn--primary', text: 'Dalje →', onClick: next });
    mount(actions,
      continueButton,
      el('button', { class: 'btn', text: '🔊 Pročitaj objašnjenje',
                     onClick: () => tts.speak(result.feedback || result.correct_text) }),
    );
    stage.querySelector('.question').insertBefore(panel, actions);
    continueButton.focus();
  }

  function showSummary(summary) {
    const rate = summary.asked ? summary.correct / summary.asked : 0;
    mount(root, el('div', { class: 'study' }, [
      el('div', { class: 'grid mb2' }, [
        statTile(summary.asked, 'odgovoreno'),
        statTile(summary.correct, 'tačno', 'mastered'),
        statTile(summary.asked - summary.correct, 'netačno', 'weak'),
        statTile(percent(rate), 'uspešnost'),
      ]),

      summary.wrong.length
        ? el('div', { class: 'card' }, [
            el('div', { class: 'card__head' }, ['Ovo si pogrešio', el('small', { text: 'vratiće se uskoro' })]),
            el('div', { class: 'list' }, summary.wrong.map((item) =>
              el('div', { class: 'list__row' }, [
                el('div', { class: 'list__main' }, [
                  el('div', { class: 'list__title', text: item.stem }),
                  el('div', { class: 'list__meta', text: `${typeLabel(item.type)}${item.topic ? ' · ' + item.topic : ''}` }),
                ]),
              ]))),
          ])
        : el('div', { class: 'card' }, [
            el('div', { class: 'card__body center' }, [
              el('div', { style: { fontSize: '34px' }, text: '🎯' }),
              el('div', { class: 'mt1', text: 'Sve tačno u ovoj sesiji.' }),
            ]),
          ]),

      summary.by_topic.length > 1
        ? el('div', { class: 'card' }, [
            el('div', { class: 'card__head' }, ['Po temama']),
            el('div', { class: 'list' }, summary.by_topic.map((item) =>
              el('div', { class: 'list__row' }, [
                el('div', { class: 'list__main' }, [item.name]),
                el('span', {
                  class: `badge ${item.correct === item.asked ? 'badge--good'
                    : (item.correct === 0 ? 'badge--bad' : 'badge--warn')}`,
                  text: `${item.correct}/${item.asked}`,
                }),
              ]))),
          ])
        : null,

      el('div', { class: 'btn-row' }, [
        el('button', { class: 'btn btn--primary', text: 'Nova sesija', onClick: () => onFinished(true) }),
        el('button', { class: 'btn', text: 'Nazad na predmet', onClick: () => onFinished(false) }),
      ]),
    ]));
    reloadTree();
  }

  next();
}

function readable(question, renderer) {
  const stem = String(question.stem).replace(/\{\{\d+\}\}/g, ' praznina ');
  // Cita se redosled SA EKRANA (izmesan), ne originalni iz baze.
  const options = (renderer && renderer.options) || question.presentation.options || [];
  if (!options.length) return stem;
  return stem + '. ' + options.map((text, index) => `${'ABCDEFGH'[index]}: ${text}`).join('. ');
}
