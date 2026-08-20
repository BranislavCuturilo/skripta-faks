// Kartica „Verzija i ažuriranje".
//
// Preuzimanje i ugradnja su namerno razdvojeni. Ugradnja se dešava tek pri
// sledećem pokretanju, jer aplikacija dok radi drži svoje fajlove otvorene i
// ne može da ih prepiše ispod sebe. Zato posle preuzimanja ne piše „Gotovo"
// nego „pokreni ponovo" — to je stvarno preostali korak.

import { api, followJob } from '../api.js';
import { el, mount, markdown, toast } from '../dom.js';

export function updateCard() {
  const body = el('div', { class: 'card__body' }, [
    el('div', { class: 'flex' }, [
      el('div', { class: 'spinner' }), 'Proveravam ima li novije verzije...',
    ]),
  ]);

  const card = el('div', { class: 'card' }, [
    el('div', { class: 'card__head' }, ['🔄 Verzija i ažuriranje']),
    body,
  ]);

  load();
  return card;

  async function load() {
    try {
      draw((await api.get('/api/update/check')).update);
    } catch (error) {
      mount(body,
        el('div', { class: 'muted', text: `Provera nije uspela: ${error.message}` }),
        el('div', { class: 'btn-row mt2' }, [checkButton()]));
    }
  }

  function draw(state) {
    const current = el('div', { class: 'field__hint mt1', text: `Trenutna verzija: ${state.current}` });

    if (state.pending) {
      mount(body,
        el('div', { class: 'flex' }, [
          el('span', { class: 'badge badge--good', text: 'preuzeto' }),
          el('strong', { text: `Verzija ${state.pending.version} čeka ugradnju.` }),
        ]),
        el('div', { class: 'mt1',
                    text: 'Ugradiće se sama kad sledeći put pokreneš aplikaciju: zatvori crni ' +
                          'prozor konzole i klikni ponovo na ikonicu.' }),
        el('div', { class: 'btn-row mt2' }, [
          el('button', {
            class: 'btn btn--sm',
            text: 'Odustani',
            onClick: async (event) => {
              event.currentTarget.disabled = true;
              try {
                await api.post('/api/update/cancel', {});
                toast('Preuzeta verzija je obrisana');
              } catch (error) {
                toast(error.message, 'bad');
              }
              load();
            },
          }),
        ]),
        current);
      return;
    }

    if (state.error) {
      mount(body,
        el('div', { class: 'muted', text: state.error }),
        el('div', { class: 'btn-row mt2' }, [checkButton()]),
        current);
      return;
    }

    if (!state.available) {
      mount(body,
        el('div', { class: 'flex' }, [
          el('span', { class: 'badge badge--good', text: 'aktuelno' }),
          'Imaš najnoviju verziju.',
        ]),
        el('div', { class: 'btn-row mt2' }, [checkButton()]),
        current);
      return;
    }

    mount(body,
      el('div', { class: 'flex' }, [
        el('span', { class: 'badge badge--accent', text: 'novo' }),
        el('strong', { text: `Dostupna je verzija ${state.latest}` }),
      ]),
      state.notes
        ? el('details', { class: 'mt1' }, [
            el('summary', { class: 'small muted', style: { cursor: 'pointer' }, text: 'Šta je novo' }),
            el('div', { class: 'prose mt1', html: markdown(state.notes) }),
          ])
        : null,
      el('div', { class: 'btn-row mt2' }, [
        el('button', {
          class: 'btn btn--primary',
          text: '⬇ Preuzmi i ažuriraj',
          onClick: (event) => start(event.currentTarget, state),
        }),
        el('a', { class: 'btn btn--sm', href: state.url, target: '_blank', rel: 'noopener',
                  text: 'Vidi šta se menja' }),
      ]),
      el('div', { class: 'field__hint mt1',
                  text: 'Tvoja pitanja, materijali i napredak se ne diraju — menja se samo kod.' }),
      current);
  }

  function checkButton() {
    return el('button', {
      class: 'btn btn--sm',
      text: 'Proveri ponovo',
      onClick: (event) => { event.currentTarget.disabled = true; load(); },
    });
  }

  async function start(button, state) {
    button.disabled = true;
    const progress = el('div', { class: 'flex mt2' }, [
      el('div', { class: 'spinner' }), 'Preuzimam...',
    ]);
    button.after(progress);

    try {
      const { job } = await api.post('/api/update/download',
                                     { version: state.latest, url: state.download });
      const finished = await followJob(job.id, (tick) => {
        mount(progress, el('div', { class: 'spinner' }), tick.message || 'Preuzimam...');
      });
      if (finished.status !== 'done') {
        throw new Error(finished.error || 'Preuzimanje je prekinuto.');
      }
      toast('Nova verzija je preuzeta', 'good');
      load();
    } catch (error) {
      mount(progress, el('span', { class: 'muted', text: error.message }));
      button.disabled = false;
    }
  }
}
