// Predlozi za nadogradnju same aplikacije.
//
// Nije za pisanje koda — nego za pretvaranje "smeta mi ovo" u nalog koji plaćeni
// AI asistent može da izvrši bez nagađanja. Aplikacija predlog piše i tu joj se
// posao završava; kod menja čovek, kroz git.

import { api, followJob } from '../api.js';
import { el, mount, modal, toast, when, bytes, markdown, confirmDialog } from '../dom.js';
import { store } from '../store.js';

const TEMPLATE = `Šta me muči:
`+
`\nGde sam to primetio (koji ekran, koji tip pitanja):
`+
`\nŠta sam očekivao da se desi:
`+
`\nŠta ne sme da se pokvari:
`;

export async function proposals(root) {
  const listBox = el('div');
  const jobBox = el('div');

  async function draw() {
    mount(listBox, el('div', { class: 'flex' }, [el('div', { class: 'spinner' }), 'Učitavam...']));
    const payload = await api.get('/api/proposals');

    if (!payload.proposals.length) {
      mount(listBox, el('div', { class: 'empty' }, [
        el('div', { class: 'empty__title', text: 'Još nema predloga' }),
        el('div', { text: 'Kad ti nešto zasmeta u aplikaciji — opiši to gore.' }),
      ]));
      return;
    }

    mount(listBox, el('div', { class: 'list' }, payload.proposals.map((item) =>
      el('div', { class: 'list__row' }, [
        el('div', { class: 'list__main', style: { cursor: 'pointer' },
                    onClick: () => open(item.slug) }, [
          el('div', { class: 'list__title', text: item.title }),
          el('div', { class: 'list__meta',
                      text: `predlozi/${item.slug}.md · ${bytes(item.size)} · ${when(item.created_at)}` }),
        ]),
        el('button', { class: 'btn btn--sm', text: 'Otvori', onClick: () => open(item.slug) }),
        el('button', {
          class: 'btn btn--sm btn--ghost', text: '🗑',
          onClick: async () => {
            if (!await confirmDialog('Obrisati predlog?', item.title)) return;
            await api.del(`/api/proposals/${item.slug}`);
            toast('Obrisano');
            draw();
          },
        }),
      ]))));
  }

  async function open(slug) {
    const payload = await api.get(`/api/proposals/${slug}`);
    const brief = extractBrief(payload.text);

    modal({
      wide: true,
      title: payload.title,
      body: el('div', {}, [
        brief
          ? el('div', { class: 'card' }, [
              el('div', { class: 'card__head' }, [
                'Nalog za AI asistenta',
                el('small', { text: 'ovo kopiraš' }),
              ]),
              el('div', { class: 'card__body' }, [
                el('div', { class: 'small muted mb1',
                            text: 'Otvori plaćenog asistenta u folderu aplikacije, priloži mu ' +
                                  'predlozi/KONTEKST-ZA-AI.md, pa nalepi ovo:' }),
                el('pre', { class: 'mono tiny', style: preStyle('30vh'), text: brief }),
                el('div', { class: 'btn-row mt1' }, [
                  el('button', {
                    class: 'btn btn--primary', text: '📋 Kopiraj nalog',
                    onClick: async () => {
                      await navigator.clipboard.writeText(brief);
                      toast('Kopirano', 'good');
                    },
                  }),
                ]),
              ]),
            ])
          : null,
        el('div', { class: 'prose', html: markdown(payload.text) }),
      ]),
    });
  }

  function compose() {
    const input = el('textarea', { rows: 12, text: TEMPLATE });

    modal({
      wide: true,
      title: 'Novi predlog',
      confirmText: 'Pošalji Gemini-ju',
      body: el('div', {}, [
        el('div', { class: 'small muted mb1',
                    text: 'Piši svojim rečima. Ne moraš da znaš kako se to rešava — to je posao ' +
                          'ovog koraka. Reci šta te muči, gde, i šta ne sme da se pokvari.' }),
        input,
        el('div', { class: 'field__hint mt1',
                    text: 'Primer: „Kad učim formule hoću da ih napišem rukom na papiru i slikam, ' +
                          'ali to sad radi samo za matematiku. Nemoj da diraš postojeća pitanja."' }),
      ]),
      onConfirm: async () => {
        const text = input.value.trim();
        if (text.length < 15 || text === TEMPLATE.trim()) {
          toast('Opiši malo detaljnije — bar rečenicu-dve.', 'bad');
          return false;
        }
        if (!store.settings.gemini_api_key_set) {
          toast('Prvo unesi Gemini API ključ u Podešavanjima.', 'bad');
          return false;
        }
        run(text);
      },
    });
  }

  async function run(text) {
    const label = el('div', { class: 'grow', text: 'Pokrećem...' });
    mount(jobBox, el('div', { class: 'job' }, [el('div', { class: 'spinner' }), label]));

    let job;
    try {
      job = (await api.post('/api/proposals', { request: text })).job;
    } catch (error) {
      mount(jobBox);
      toast(error.message, 'bad');
      return;
    }

    const finished = await followJob(job.id, (tick) => {
      label.textContent = tick.message || 'Radim...';
    });
    mount(jobBox);

    if (finished.status === 'failed') {
      toast(finished.error || 'Predlog nije napisan.', 'bad');
      return;
    }
    const result = finished.result || {};
    toast(result.feasible === false
      ? 'Predlog je napisan, ali zahtev se ne uklapa u pravila projekta — pročitaj ga.'
      : 'Predlog je zapisan u predlozi/', result.feasible === false ? 'bad' : 'good');
    await draw();
    if (result.slug) open(result.slug);
  }

  async function showContext() {
    const payload = await api.get('/api/proposals/context');
    modal({
      wide: true,
      title: 'Mapa projekta (KONTEKST-ZA-AI.md)',
      body: el('div', {}, [
        el('div', { class: 'small muted mb1',
                    text: 'Ovo priložiš asistentu uz nalog. Generisano je iz stvarnog koda — ' +
                          'ne piše se rukom.' }),
        el('pre', { class: 'mono tiny', style: preStyle('52vh'), text: payload.text }),
        el('div', { class: 'btn-row mt1' }, [
          el('button', {
            class: 'btn btn--primary', text: '📋 Kopiraj mapu',
            onClick: async () => {
              await navigator.clipboard.writeText(payload.text);
              toast('Kopirano', 'good');
            },
          }),
          el('button', {
            class: 'btn', text: '⟳ Osveži iz koda',
            onClick: async (event) => {
              event.currentTarget.disabled = true;
              try {
                await api.post('/api/proposals/context/refresh', {});
                toast('Mapa je osvežena', 'good');
              } catch (error) {
                toast(error.message, 'bad');
              }
            },
          }),
        ]),
      ]),
    });
  }

  mount(root,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Kad ti aplikacija ne radi ono što ti treba']),
      el('div', { class: 'card__body prose' }, [
        el('p', { text: 'Ne moraš sam da pišeš kod. Opišeš svojim rečima šta ti fali, Gemini to ' +
                        'prevede u konkretan nalog — koji fajlovi se diraju, šta se menja, šta ne ' +
                        'sme da se pokvari — i taj nalog odneseš plaćenom AI asistentu koji ume ' +
                        'da napiše kod.' }),
        el('p', {}, [
          el('strong', { text: 'Zašto ovako, a ne odmah asistentu: ' }),
          'on ne zna ovu aplikaciju. Ako mu samo kažeš „dodaj mi ovo", počeće da nagađa — ',
          'izmisliće fajlove, dodaće biblioteku koju ovaj projekat namerno nema, i polomiti ',
          'nešto treće. Mapa projekta i tačan nalog su ono što ga u tome sprečava.',
        ]),
        el('div', { class: 'btn-row mt2' }, [
          el('button', { class: 'btn btn--primary', text: '+ Novi predlog', onClick: compose }),
          el('button', { class: 'btn', text: '🗺 Pogledaj mapu projekta', onClick: showContext }),
        ]),
      ]),
    ]),
    jobBox,
    listBox,
  );

  draw();
}

function extractBrief(text) {
  // Nalog stoji u poslednjem ``` bloku fajla, ispod naslova "Nalog za AI asistenta".
  const marker = text.indexOf('Nalog za AI asistenta');
  const region = marker >= 0 ? text.slice(marker) : text;
  const found = region.match(/```\s*\n([\s\S]*?)```/);
  return found ? found[1].trim() : '';
}

function preStyle(maxHeight) {
  return {
    whiteSpace: 'pre-wrap', background: 'var(--bg)', padding: '12px',
    borderRadius: '7px', maxHeight, overflow: 'auto', margin: '0',
  };
}
