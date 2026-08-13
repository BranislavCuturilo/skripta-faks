// Podešavanja: AI ključ, modeli, agresivnost, govor, izgled, potrošnja.

import { api } from '../api.js';
import { el, mount, field, toast, when } from '../dom.js';
import { store, saveSettings } from '../store.js';
import * as tts from '../tts.js';
import { networkCard } from './network.js';

export async function settings(root) {
  const values = store.settings;
  const modelBox = el('div');
  const usageBox = el('div');

  // ------------------------------------------------------------ AI ključ

  const keyInput = el('input', {
    type: 'password',
    // Ne pisati "AIza..." kao placeholder: u proporcionalnom fontu veliko I
    // izgleda kao malo L, pa ljudi kucaju "Alza".
    placeholder: values.gemini_api_key_set ? '••••••••••••' : 'nalepi ključ ovde',
    autocomplete: 'off',
  });
  const keyStatus = el('div', {
    class: 'field__hint',
    text: values.gemini_api_key_set
      ? `Ključ je sačuvan (${values.gemini_api_key_hint}).`
      : 'Ključ još nije unet — AI funkcije neće raditi.',
  });

  const testButton = el('button', {
    class: 'btn btn--primary', text: 'Proveri i sačuvaj ključ',
    onClick: async () => {
      testButton.disabled = true;
      keyStatus.textContent = 'Proveravam...';
      try {
        const result = await api.post('/api/settings/test-key',
                                      { gemini_api_key: keyInput.value, save: true });
        keyStatus.textContent = `Ključ radi. Dostupno modela: ${result.count}.`;
        keyInput.value = '';
        toast('Ključ je sačuvan', 'good');
        await refreshStore();
        loadModels();
      } catch (error) {
        keyStatus.textContent = error.message;
        toast(error.message, 'bad');
      } finally {
        testButton.disabled = false;
      }
    },
  });

  async function refreshStore() {
    const payload = await api.get('/api/settings');
    store.settings = payload.settings;
  }

  const TIERS = [
    ['fast', 'model_fast', 'Brz i jeftin', 'Za sitne poslove — najmanje troši kvotu.'],
    ['standard', 'model_standard', 'Standardni', 'Generisanje pitanja i ocenjivanje.'],
    ['strong', 'model_strong', 'Najjači', 'Foto-zadaci, teško ocenjivanje, predlozi za nadogradnju.'],
    ['tts', 'model_tts', 'Glas', 'Koristi se samo ako je izgovor podešen na Gemini glas.'],
  ];

  async function loadModels(refresh = false) {
    mount(modelBox, el('div', { class: 'flex' }, [
      el('div', { class: 'spinner' }), refresh ? 'Pitam Google šta je dostupno...' : 'Učitavam...',
    ]));

    let payload;
    try {
      payload = refresh
        ? await api.post('/api/models/refresh', {})
        : await api.get('/api/models');
    } catch (error) {
      mount(modelBox, el('div', { class: 'muted small', text: error.message }));
      return;
    }

    const list = payload.models || [];
    const byTier = Object.fromEntries((payload.status?.tiers || []).map((item) => [item.tier, item]));
    store.models = payload.status || store.models;

    if (refresh && (payload.changes || []).length) {
      for (const change of payload.changes) {
        toast(`${change.tier}: ${change.from} → ${change.to}`, 'good');
      }
    }

    const picker = ([tier, key, label, hint]) => {
      const info = byTier[tier] || {};
      const options = [
        el('option', {
          value: '',
          selected: !info.manual,
          text: `Automatski${info.model ? ` — sada: ${info.model}` : ''}`,
        }),
        ...list.map((name) => el('option', {
          value: name, text: name, selected: info.manual && info.model === name,
        })),
      ];

      return el('div', { class: 'field' }, [
        el('span', { class: 'field__label' }, [
          label,
          info.retired ? el('span', { class: 'badge badge--bad', text: 'penzionisan' }) : null,
          info.missing ? el('span', { class: 'badge badge--warn', text: 'nema ga na tvom ključu' }) : null,
        ]),
        el('select', {
          onChange: async (event) => {
            await saveSettings({ [key]: event.target.value });
            toast('Sačuvano', 'good');
            loadModels();
          },
        }, options),
        el('div', { class: 'field__hint', text: hint }),
      ]);
    };

    mount(modelBox,
      el('div', { class: 'small muted mb2' }, [
        'Nazivi Gemini modela se menjaju — aplikacija ih zato ne drži tvrdo upisane nego bira ',
        'iz spiska koji vrati tvoj ključ. Ostavi „Automatski" i sam će preći na noviji kad ovaj ',
        'bude penzionisan.',
      ]),
      ...TIERS.map(picker),
      el('div', { class: 'btn-row mt1' }, [
        el('button', { class: 'btn', text: '⟳ Osveži spisak modela',
                       onClick: () => loadModels(true) }),
        el('span', { class: 'tiny faint',
                     text: payload.status?.checked_at
                       ? `${payload.status.available_count} dostupnih · provereno ${when(payload.status.checked_at)}`
                       : 'spisak još nije učitan sa tvog ključa' }),
      ]),
      !payload.key_set && !list.length
        ? el('div', { class: 'field__hint mt1',
                      text: 'Unesi ključ pa pritisni „Osveži spisak" — dok toga nema, koriste se ' +
                            'podrazumevani nazivi i poziv može da padne ako su penzionisani.' })
        : null,
    );
  }

  // ------------------------------------------------------------ govor

  const engineSelect = el('select', {
    onChange: async (event) => {
      await saveSettings({ tts_engine: event.target.value });
      drawVoices();
    },
  }, [
    el('option', { value: 'browser', text: 'Browser (Windows glasovi) — besplatno, radi i na telefonu',
                   selected: values.tts_engine === 'browser' }),
    el('option', { value: 'windows', text: 'Zvučnik računara (PowerShell)',
                   selected: values.tts_engine === 'windows' }),
    el('option', { value: 'gemini', text: 'Gemini glas — prirodniji, troši kvotu',
                   selected: values.tts_engine === 'gemini' }),
  ]);

  const voiceBox = el('div');
  function drawVoices() {
    const engine = store.settings.tts_engine;
    if (engine !== 'browser') { mount(voiceBox); return; }
    const list = tts.voices();
    const local = tts.localVoices();
    mount(voiceBox, field('Glas', el('select', {
      onChange: (event) => saveSettings({ tts_voice: event.target.value }),
    }, [
      el('option', { value: '', text: local.length ? `Automatski (${local[0].name})` : 'Automatski' }),
      ...list.map((voice) => el('option', {
        value: voice.name, text: `${voice.name} (${voice.lang})`,
        selected: voice.name === store.settings.tts_voice,
      })),
    ]), local.length ? '' : 'Nema instaliranih srpskih glasova — Windows ih dodaje kroz Settings → Time & Language → Speech.'));
  }
  if (tts.available()) window.speechSynthesis.onvoiceschanged = drawVoices;

  // ------------------------------------------------------------ potrošnja

  async function loadUsage() {
    const payload = await api.get('/api/ai/usage');
    if (!payload.totals.length) {
      mount(usageBox, el('div', { class: 'muted small', text: 'Još nema AI poziva.' }));
      return;
    }
    mount(usageBox,
      el('div', { class: 'list mb2' }, payload.totals.map((row) =>
        el('div', { class: 'list__row' }, [
          el('div', { class: 'list__main', text: row.purpose }),
          el('span', { class: 'badge', text: `${row.calls} poziva` }),
          el('span', { class: 'badge badge--good', text: `${row.succeeded} ok` }),
          row.prompt_tokens
            ? el('span', { class: 'badge badge--accent',
                           text: `${Math.round(row.prompt_tokens / 1000)}k ulaz` })
            : null,
          row.output_tokens
            ? el('span', { class: 'badge badge--accent',
                           text: `${Math.round(row.output_tokens / 1000)}k izlaz` })
            : null,
        ]))),
      el('div', { class: 'field__label', text: 'Poslednji pozivi' }),
      el('div', { class: 'list' }, payload.recent.slice(0, 12).map((row) =>
        el('div', { class: 'list__row' }, [
          el('div', { class: 'list__main' }, [
            el('div', { class: 'list__title', text: `${row.purpose} · ${row.model}` }),
            el('div', { class: 'list__meta',
                        text: `${when(row.created_at)} · ${row.duration_ms} ms${row.error ? ' · ' + row.error : ''}` }),
          ]),
          el('span', { class: `badge ${row.ok ? 'badge--good' : 'badge--bad'}`, text: row.ok ? 'ok' : 'greška' }),
        ]))));
  }

  const numberField = (key, label, min, max, hint) => field(label, el('input', {
    type: 'number', min: String(min), max: String(max), value: String(values[key]),
    onChange: (event) => saveSettings({ [key]: Number(event.target.value) }).then(() => toast('Sačuvano', 'good')),
  }), hint);

  const checkField = (key, label) => el('label', { class: 'checkline' }, [
    el('input', { type: 'checkbox', checked: !!values[key],
                  onChange: (event) => saveSettings({ [key]: event.target.checked }) }),
    label,
  ]);

  mount(root,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['AI ključ', el('small', { text: 'Gemini je besplatan' })]),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'small muted mb1' }, [
          'Ključ uzimaš na ',
          el('a', { href: 'https://aistudio.google.com/api-keys', target: '_blank',
                    rel: 'noopener', text: 'aistudio.google.com/api-keys' }),
          '. Čuva se u tvojoj lokalnoj bazi i ne šalje se nigde osim Google-u.',
        ]),
        el('div', { class: 'field__hint mb1' }, [
          el('strong', { text: 'Stariji ključ prestao da radi? ' }),
          'Google gasi stari tip ključa („standard") — svi prestaju da rade tokom septembra 2026. ',
          'Napravi novi na linku iznad; novi su automatski „auth" i rade dalje. ',
          'Pitanja i napredak ostaju.',
        ]),
        field('Gemini API ključ', keyInput),
        keyStatus,
        el('div', { class: 'btn-row mt1' }, [
          testButton,
          values.gemini_api_key_set
            ? el('button', {
                class: 'btn btn--danger', text: 'Ukloni ključ',
                onClick: async () => {
                  await api.del('/api/settings/api-key');
                  toast('Ključ je uklonjen');
                  settings(root);
                },
              })
            : null,
        ]),
      ]),
    ]),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Modeli', el('small', { text: 'jači za teže poslove' })]),
      el('div', { class: 'card__body' }, [modelBox]),
    ]),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Učenje']),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'row2' }, [
          numberField('aggressiveness', 'Agresivnost (1–5)', 1, 5,
                      '1 = može po nešto i da ne znam · 5 = moram sve da znam'),
          numberField('session_length', 'Pitanja po sesiji', 1, 200),
        ]),
        el('div', { class: 'row2' }, [
          numberField('generate_variants', 'Varijacija po pitanju', 0, 4,
                      'Isto znanje provereno iz drugog ugla.'),
          numberField('batch_char_budget', 'Znakova gradiva po pozivu', 4000, 400000,
                      'Veći broj = manje poziva, više tokena po pozivu.'),
        ]),
        checkField('auto_explain', 'Zovi AI za objašnjenje kad ga nema unapred'),
        checkField('auto_strategy', 'Neka sistem sam prilagođava strategiju posle generisanja'),
      ]),
    ]),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Izgovor teksta']),
      el('div', { class: 'card__body' }, [
        field('Motor', engineSelect),
        voiceBox,
        numberField('tts_rate', 'Brzina', 0.5, 2),
        el('div', { class: 'btn-row mt1' }, [
          el('button', { class: 'btn', text: '🔊 Probaj',
                         onClick: () => tts.speak('Ovo je proba izgovora. Integral je granična vrednost sume.') }),
        ]),
      ]),
    ]),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Izgled i jezik']),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'row2' }, [
          field('Tema', el('select', {
            onChange: (event) => saveSettings({ theme: event.target.value }),
          }, [
            el('option', { value: 'dark', text: 'Tamna', selected: values.theme === 'dark' }),
            el('option', { value: 'light', text: 'Svetla', selected: values.theme === 'light' }),
          ])),
          field('Jezik pitanja', el('select', {
            onChange: (event) => saveSettings({ question_language: event.target.value }),
          }, [
            el('option', { value: 'sr', text: 'Srpski (latinica)', selected: values.question_language === 'sr' }),
            el('option', { value: 'sr-cyrl', text: 'Srpski (ćirilica)', selected: values.question_language === 'sr-cyrl' }),
            el('option', { value: 'en', text: 'Engleski', selected: values.question_language === 'en' }),
          ])),
        ]),
      ]),
    ]),

    await networkCard(),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Potrošnja AI poziva']),
      el('div', { class: 'card__body' }, [usageBox]),
    ]),

    el('div', { class: 'center faint tiny mt2',
                text: `skripta-faks ${store.version} · sve radi lokalno, bez ijedne biblioteke` }),
  );

  loadModels();
  drawVoices();
  loadUsage();
}
