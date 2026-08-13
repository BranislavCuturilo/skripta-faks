// Uputstvo unutar aplikacije.
//
// Nije prepis docs/UPUTSTVO.md nego njegova skraćena verzija koja ZNA tvoje
// stanje: da li je ključ unet, koja je adresa za telefon, ima li već predmeta.
// Uputstvo koje ti kaže "unesi ključ" kad si ga već uneo niko ne čita do kraja.

import { el, mount } from '../dom.js';
import { store } from '../store.js';
import { networkCard } from './network.js';

export async function guide(root) {
  const settings = store.settings;
  const hasKey = !!settings.gemini_api_key_set;
  const hasCategory = store.tree.length > 0;
  const hasQuestions = (store.stats.questions || 0) > 0;

  mount(root,
    el('div', { class: 'card' }, [
      el('div', { class: 'card__body' }, [
        el('div', { class: 'small muted',
                    text: 'Od nule do prve sesije učenja. Puno uputstvo, sa rešavanjem problema, ' +
                          'stoji u docs/UPUTSTVO.md u folderu aplikacije.' }),
      ]),
    ]),

    step(1, 'Gemini API ključ', hasKey, [
      el('p', {}, [
        'Aplikacija radi i bez ključa, ali samo sa pitanjima koja već imaš. ',
        'Bez njega ne može da generiše nova, ni da oceni odgovor koji nije doslovan. ',
        el('strong', { text: 'Ključ je besplatan.' }),
      ]),
      el('ol', {}, [
        el('li', {}, [
          'Otvori ',
          el('a', { href: 'https://aistudio.google.com/api-keys', target: '_blank',
                    rel: 'noopener', text: 'aistudio.google.com/api-keys' }),
        ]),
        el('li', { text: 'Prijavi se bilo kojim Google nalogom' }),
        el('li', { text: 'Klikni Create API key (ako pita za projekat — izaberi bilo koji)' }),
        el('li', {}, [
          'Kopiraj ključ — počinje sa ',
          el('code', { text: 'AIza' }),
          ' (veliko i, ne malo L)',
        ]),
        el('li', { text: 'Ovde u Podešavanjima ga nalepi i pritisni „Proveri i sačuvaj"' }),
      ]),
      el('div', { class: 'small faint',
                  text: 'Ključ stoji u data/skripta.db na tvom računaru, van gita. ' +
                        'Ne šalje se nikome osim Google-u, i nikad ti se ne prikazuje ceo nazad.' }),
      el('div', { class: 'feedback feedback--partial mt1' }, [
        el('div', { class: 'feedback__verdict', text: 'Ako ti je stariji ključ prestao da radi' }),
        el('div', { class: 'feedback__body' }, [
          'Google menja tip ključa, nezavisno od modela. Stari „standard" ključevi se već ',
          'odbijaju, a tokom septembra 2026 prestaju da rade svi. Napravi novi na linku iznad ',
          '— novi su automatski „auth" i rade dalje. Pitanja, napredak i materijali ostaju.',
        ]),
      ]),
      el('div', { class: 'btn-row mt1' }, [
        el('button', { class: `btn ${hasKey ? '' : 'btn--primary'}`,
                       text: hasKey ? 'Promeni ključ' : 'Unesi ključ',
                       onClick: () => { location.hash = '#/podesavanja'; } }),
      ]),
    ]),

    step(2, 'Napravi predmet i podkategorije', hasCategory, [
      el('p', { text: 'Predmet je kategorija — npr. „Matematika 2". U njemu praviš podkategorije: ' +
                      '„Kolokvijum 1", pa unutar toga oblasti, u nedogled.' }),
      el('p', {}, [
        el('strong', { text: 'Bitno: ' }),
        'učenje na nekom čvoru obuhvata i sve ispod njega. Sesija na „Matematika 2" ' +
        'ispituje te iz svih kolokvijuma.',
      ]),
      el('div', { class: 'btn-row mt1' }, [
        el('button', { class: `btn ${hasCategory ? '' : 'btn--primary'}`, text: '+ Novi predmet',
                       onClick: () => document.getElementById('new-category').click() }),
      ]),
    ]),

    step(3, 'Ubaci materijale', (store.stats.materials || 0) > 0, [
      el('p', { text: 'Tab Materijali → prevuci fajlove. Prima PDF, Word, Excel, PowerPoint, ' +
                      'slike, snimke, tekst i titlove.' }),
      el('p', {}, [
        'Posle upload-a svaki fajl dobije oznaku: ',
        el('span', { class: 'badge badge--good', text: 'pročitano lokalno' }),
        ' — tekst je izvučen na tvom računaru i ništa nije poslato nigde; ili ',
        el('span', { class: 'badge badge--warn', text: 'ide AI-u' }),
        ' — lokalno čitanje nije dalo upotrebljiv tekst (skeniran PDF, slika, snimak), ' +
        'pa se original šalje Gemini-ju.',
      ]),
      el('div', { class: 'small faint',
                  text: 'Stari .doc / .xls / .ppt se ne čitaju — sačuvaj ih kao .docx ili PDF.' }),
    ]),

    step(4, 'Napiši šta se tačno uči', false, [
      el('p', {}, [
        'Najvažnije polje u aplikaciji (tab ',
        el('strong', { text: 'Pregled' }),
        '). Ograničava obim i ide u ',
        el('strong', { text: 'svaki' }),
        ' prompt.',
      ]),
      el('pre', { class: 'mono tiny', style: exampleStyle(),
                  text: 'Uči se samo do lekcije 5. Preskoči dokaze teorema.' }),
      el('pre', { class: 'mono tiny', style: exampleStyle(),
                  text: 'Fokus na zadacima, ne na definicijama.\nOznake koristi kao u skripti.' }),
      el('p', { class: 'small',
                text: 'Uputstvo se nasleđuje: ono što napišeš na predmetu važi i za sve ' +
                      'kolokvijume ispod. Ispod polja vidiš celo uputstvo koje model stvarno dobija.' }),
    ]),

    step(5, 'Generiši pitanja', hasQuestions, [
      el('p', { text: 'Tab Generisanje. Na vrhu vidiš plan PRE nego što potrošiš išta: ' +
                      'koliko poziva, koliko gradiva, procena tokena, koliko pitanja se očekuje.' }),
      el('p', {}, [
        'Ako Gemini ne uspe ili si potrošio kvotu: ',
        el('strong', { text: '📤 Izvezi prompt' }),
        ' → nalepi u Claude → kopiraj njegov odgovor → ',
        el('strong', { text: '📥 Nalepi odgovor' }),
        '. Prolazi kroz istu proveru kao Gemini-jev.',
      ]),
      el('div', { class: 'small faint',
                  text: 'Odbijena pitanja nisu greška — to je zaštita. Pitanje bez tačnog ' +
                        'odgovora ne ulazi u bazu polomljeno.' }),
    ]),

    step(6, 'Uči', (store.stats.attempts || 0) > 0, [
      el('p', {}, [
        el('strong', { text: 'Agresivnost' }),
        ' odlučuje koliko strogo se meri da nešto „znaš". ',
        '1 = može po nešto i da ne znam (prag 70%, duži razmaci). ',
        '5 = moram sve da znam (prag 95%, sve se vrti češće).',
      ]),
      el('p', { text: 'Uz svako pitanje imaš alatke:' }),
      el('div', { class: 'list' }, [
        toolRow('📝 Beleška', 'Tvoja beleška uz pitanje — preživljava svaku izmenu pitanja'),
        toolRow('🚩 Proveriti', 'Hoću ovo ponovo da pogledam'),
        toolRow('🔍 Provera u fajlu', 'Sumnjam da se ponavlja ili da je AI pogrešio'),
        toolRow('🗑 Nebitno', 'Za uklanjanje'),
        toolRow('⏭ Preskoči', 'Ne sada — ali ostaje u igri'),
        toolRow('🚫 Zanemari zauvek', 'Nikad me više ne pitaj ovo'),
      ]),
      el('div', { class: 'small faint mt1',
                  text: 'Sve označeno kasnije nalaziš u tabu Pitanja, kroz filter po oznaci.' }),
    ]),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['7. Uči i sa telefona']),
      el('div', { class: 'card__body' }, [
        el('p', { text: 'Server sluša na celoj mreži, pa telefon na istom Wi-Fi-ju može da ga ' +
                        'otvori. To je ono što omogućava tip zadatka „Uradi zadatak": rešiš na ' +
                        'papiru, slikaš telefonom, AI proverava postupak.' }),
      ]),
    ]),
    await networkCard(),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['8. Bekap']),
      el('div', { class: 'card__body' }, [
        el('p', {}, [
          'Sve tvoje je u folderu ', el('code', { text: 'data/' }), ': baza sa pitanjima i ',
          'napretkom, i tvoji fajlovi u originalu. Bekap = kopiraj taj folder.',
        ]),
      ]),
    ]),

    el('div', { class: 'card' }, [
      el('div', { class: 'card__head' }, ['Kad ti nešto zafali']),
      el('div', { class: 'card__body' }, [
        el('p', { text: 'Ako aplikacija ne radi nešto što ti treba, ne moraš sam da pišeš kod. ' +
                        'Tab Predlozi opišeš svojim rečima šta ti fali, Gemini to prevede u ' +
                        'konkretan nalog (koji fajlovi, šta se menja, šta ne sme da se pokvari), ' +
                        'i taj nalog odneseš plaćenom AI asistentu koji ume da napiše kod.' }),
        el('div', { class: 'btn-row mt1' }, [
          el('button', { class: 'btn', text: 'Otvori Predloge',
                         onClick: () => { location.hash = '#/predlozi'; } }),
        ]),
      ]),
    ]),
  );
}

function step(number, title, done, body) {
  return el('div', { class: 'card' }, [
    el('div', { class: 'card__head' }, [
      `${number}. ${title}`,
      done ? el('span', { class: 'badge badge--good', text: '✓ urađeno' }) : null,
    ]),
    el('div', { class: 'card__body prose' }, body),
  ]);
}

function toolRow(label, description) {
  return el('div', { class: 'list__row' }, [
    el('div', { style: { minWidth: '170px' }, text: label }),
    el('div', { class: 'list__main small muted', text: description }),
  ]);
}

function exampleStyle() {
  return {
    whiteSpace: 'pre-wrap', background: 'var(--bg)', padding: '10px',
    borderRadius: '7px', margin: '0 0 8px',
  };
}
