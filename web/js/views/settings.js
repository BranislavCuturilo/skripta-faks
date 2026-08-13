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
    type: 'password', placeholder: values.gemini_api_key_set ? '••••••••••••' : 'AIza...',
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

  async function loadModels() {
    if (!store.settings.gemini_api_key_set) {
      mount(modelBox, el('div', { class: 'muted small', text: 'Unesi ključ pa biraj modele.' }));
      return;
    }
    mount(modelBox, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Učitavam modele...']));

    let payload;
    try {
      payload = await api.get('/api/models');
    } catch (error) {
      mount(modelBox, el('div', { class: 'muted small', text: error.message }));
      return;
    }

    const options = payload.models || [];
    const picker = (key, label, hint) => field(label, el('select', {
      onChange: (event) => saveSettings({ [key]: event.target.value }).then(() => toast('Sačuvano', 'good')),
    }, options.map((model) => el('option', {
      value: model.name, text: model.label, selected: model.name === store.settings[key],
    }))), hint);

    mount(modelBox,
      picker('model_fast', 'Brz i jeftin', 'Za sitne poslove — najmanje troši kvotu.'),
      picker('model_standard', 'Standardni', 'Generisanje pitanja i ocenjivanje.'),
      picker('model_strong', 'Najjači', 'Foto-zadaci i teško ocenjivanje.'));
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
          el('a', { href: 'https://aistudio.google.com/apikey', target: '_blank',
                    rel: 'noopener', text: 'aistudio.google.com/apikey' }),
          '. Čuva se u tvojoj lokalnoj bazi i ne šalje se nigde osim Google-u.',
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
