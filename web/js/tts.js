// Izgovor teksta. Tri motora, isti poziv.
//
// `browser` je podrazumevan: Web Speech API je u samom browseru, radi i na
// telefonu, ne trosi kvotu i ne salje tekst nikome.

import { api } from './api.js';
import { store } from './store.js';
import { toast } from './dom.js';

let currentAudio = null;

export function available() {
  return 'speechSynthesis' in window;
}

export function voices() {
  return available() ? window.speechSynthesis.getVoices() : [];
}

export function localVoices() {
  // Srpski, hrvatski i bosanski glasovi su medjusobno razumljivi za ovu svrhu.
  return voices().filter((voice) => /^(sr|hr|bs)/i.test(voice.lang));
}

export function stop() {
  if (available()) window.speechSynthesis.cancel();
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
}

export async function speak(text) {
  const clean = String(text || '').replace(/\{\{\d+\}\}/g, ' praznina ').trim();
  if (!clean) return;

  stop();
  const engine = store.settings.tts_engine || 'browser';

  if (engine === 'browser') {
    if (!available()) { toast('Ovaj browser nema ugrađeni govor.', 'bad'); return; }
    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = Number(store.settings.tts_rate) || 1;
    const preferred = store.settings.tts_voice;
    const pick = voices().find((voice) => voice.name === preferred) || localVoices()[0];
    if (pick) { utterance.voice = pick; utterance.lang = pick.lang; }
    else utterance.lang = 'sr-RS';
    window.speechSynthesis.speak(utterance);
    return;
  }

  try {
    if (engine === 'windows') {
      await api.post('/api/tts', { text: clean, engine: 'windows', rate: store.settings.tts_rate });
      return;
    }
    const blob = await api.blob('/api/tts', { text: clean, engine: 'gemini' });
    currentAudio = new Audio(URL.createObjectURL(blob));
    await currentAudio.play();
  } catch (error) {
    toast(error.message, 'bad');
  }
}
