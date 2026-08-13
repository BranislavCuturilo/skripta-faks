// Kartica "otvori na telefonu".
//
// Adresa se traži od servera na svako crtanje, ne pamti se: Wi-Fi se menja,
// laptop prelazi sa kabla na bežičnu, VPN se pali i gasi. Zapamćena adresa je
// adresa koja jednog dana prestane da radi bez ikakvog objašnjenja.

import { api } from '../api.js';
import { el, toast } from '../dom.js';

export async function networkCard({ compact = false } = {}) {
  let network;
  try {
    network = (await api.get('/api/network')).network;
  } catch (error) {
    return el('div', { class: 'card' }, [
      el('div', { class: 'card__body muted', text: `Adresa nije dostupna: ${error.message}` }),
    ]);
  }

  if (!network.ready || !network.addresses.length) {
    return el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Otvori na telefonu']),
      el('div', { class: 'card__body' }, [
        el('div', { class: 'muted',
                    text: 'Računar trenutno nema mrežnu adresu — nije povezan na Wi-Fi ili kabl. ' +
                          'Poveži se pa osveži stranicu.' }),
      ]),
    ]);
  }

  const primary = network.addresses[0];
  const rest = network.addresses.slice(1);

  return el('div', { class: 'card' }, [
    el('div', { class: 'card__head' }, [
      '📱 Otvori na telefonu',
      el('small', { text: 'telefon mora da bude na istom Wi-Fi-ju' }),
    ]),
    el('div', { class: 'card__body' }, [
      el('div', {
        style: {
          fontSize: '26px', fontFamily: 'var(--mono)', fontWeight: '700',
          letterSpacing: '-0.5px', wordBreak: 'break-all', marginBottom: '10px',
        },
        text: primary.url,
      }),
      el('div', { class: 'btn-row' }, [
        copyButton(primary.url, 'Kopiraj adresu'),
        el('a', { class: 'btn btn--sm', href: primary.url, target: '_blank', rel: 'noopener',
                  text: 'Otvori ovde' }),
      ]),

      rest.length
        ? el('details', { class: 'mt2' }, [
            el('summary', { class: 'small muted', style: { cursor: 'pointer' },
                            text: `Ne radi? Probaj neku od ostalih ${rest.length} adresa` }),
            el('div', { class: 'list mt1' }, rest.map((item) =>
              el('div', { class: 'list__row' }, [
                el('div', { class: 'list__main' }, [
                  el('div', { class: 'list__title mono', text: item.url }),
                  item.hint ? el('div', { class: 'list__meta', text: item.hint }) : null,
                ]),
                copyButton(item.url, 'Kopiraj'),
              ]))),
            el('div', { class: 'field__hint mt1',
                        text: 'Adrese označene kao VirtualBox, WSL ili VPN skoro sigurno nisu ' +
                              'tvoj Wi-Fi — probaj prvo one bez napomene.' }),
          ])
        : null,

      compact ? null : el('div', { class: 'field__hint mt2' }, [
        el('strong', { text: 'Ako telefon ne može da otvori: ' }),
        'najčešće je kriv Windows firewall. Pri prvom pokretanju iskoči prozor „Allow access" ' +
        'i mora se dozvoliti za privatne mreže. Ako si to odbio: Windows Security → Firewall & ' +
        'network protection → Allow an app through firewall → pronađi Python i čekiraj Private.',
      ]),
    ]),
  ]);
}

function copyButton(text, label) {
  return el('button', {
    class: 'btn btn--sm',
    text: `📋 ${label}`,
    onClick: async (event) => {
      try {
        await navigator.clipboard.writeText(text);
        toast('Kopirano', 'good');
      } catch {
        // clipboard traži bezbedan kontekst; preko LAN IP-a ga nema, pa selektuj.
        const field = el('input', { type: 'text', value: text });
        event.currentTarget.after(field);
        field.select();
        toast('Kopiraj rukom: Ctrl+C');
      }
    },
  });
}
