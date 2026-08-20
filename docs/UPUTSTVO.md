# Uputstvo

Od nule do prve sesije učenja. Isto ovo, skraćeno, stoji i u samoj aplikaciji —
dugme **Uputstvo** u levoj koloni.

---

## 1. Instalacija

Skini **`instaliraj.bat`** sa
<https://github.com/BranislavCuturilo/skripta-faks/raw/main/instaliraj.bat>
i klikni dupli klik na njega.

To je ceo posao. Instalacija sama proveri imaš li Python, instalira ga ako
nemaš, skine aplikaciju, napravi ikonicu na desktopu i pokrene je.

**Windows će te uplašiti jednom porukom.** Piše *„Windows protected your PC"*.
To piše za svaki `.bat` fajl skinut sa interneta — ne znači da nešto nije u
redu. Klikni **More info**, pa **Run anyway**.

Instalira se u `C:\Users\<ti>\AppData\Local\skripta-faks`. Ne traži
administratorsku lozinku.

### Ako više voliš ručno

Treba ti samo **Python 3.11 ili noviji**. Ništa drugo — nema `pip install`.

Proveri da li ga već imaš: otvori *Command Prompt* i ukucaj

```
python --version
```

Ako piše verzija — gotovo. Ako piše da komanda nije pronađena, skini ga sa
<https://www.python.org/downloads/> i **obavezno čekiraj „Add python.exe to PATH"**
na prvom ekranu instalacije. To je jedini korak koji ljudi preskoče, a bez njega
`START.bat` ne radi.

Onda skini ZIP repozitorijuma, raspakuj ga gde želiš, i klikni na `START.bat`.

## 2. Pokretanje

Dupli klik na ikonicu **skripta-faks** na desktopu (ili na `START.bat` u
folderu aplikacije, ako si instalirao ručno).

Otvoriće se crni prozor (to je server — mora da ostane otvoren dok učiš) i
browser na `http://localhost:8077`.

**Gašenje:** zatvori crni prozor, ili pritisni `Ctrl+C` u njemu.

## 3. Gemini API ključ

Aplikacija radi i bez ključa — ali samo za pitanja koja već imaš. Bez njega ne
može da generiše nova pitanja, ni da oceni odgovor koji nije doslovan.

Ključ je **besplatan**.

1. Otvori <https://aistudio.google.com/api-keys>
2. Prijavi se svojim Google nalogom (bilo kojim, ne mora poslovni)
3. Klikni **Create API key**
4. Ako te pita za projekat, izaberi bilo koji ponuđeni ili **Create project**
5. Kopiraj ključ — počinje sa `AIza` (veliko *i*, ne malo *L*)

U aplikaciji: **⚙ Podešavanja** → polje *Gemini API ključ* → nalepi →
**Proveri i sačuvaj ključ**.

Dugme odmah proba ključ, ispiše koliko modela ti je dostupno i **odmah izabere
koje će koristiti**.

### Ako imaš stariji ključ koji je prestao da radi

Google menja **tip** ključa, nezavisno od modela:

- stari **standard** ključevi se već odbijaju ako nemaju ograničenja
- **tokom septembra 2026 prestaju da rade svi standard ključevi**
- novi ključevi napravljeni u AI Studiju su automatski **auth** ključevi i rade dalje

Ako ti aplikacija javi *„API ključ nije prihvaćen"* ili *„Ključ nema pravo
pristupa"*, a siguran si da si ga dobro prekopirao — ključ je verovatno stari
tip. Rešenje je da na <https://aistudio.google.com/api-keys> napraviš **novi** i
zameniš ga u Podešavanjima. Ništa drugo ne moraš da diraš; pitanja, napredak i
materijali ostaju.

**Gde ključ stoji:** u `data/skripta.db`, na tvom računaru. Ne šalje se nikome
osim Google-u. Van gita je. Aplikacija ti ga nikad ne prikazuje ceo nazad — samo
prve i poslednje četiri cifre.

### Besplatna kvota

Google daje ograničen broj poziva dnevno i po minutu. Ako pređeš, dobićeš poruku
*„Prešao si besplatnu kvotu za sada"* — sačekaj minut do dva i probaj ponovo.

Aplikacija je pravljena da to štedi:
- **jedan poziv nosi do 60.000 znakova gradiva** i traži desetine pitanja odjednom
- **odgovori se ocenjuju lokalno kad god mogu** — AI ulazi u igru samo za dopunu
  rečenice koja je promašena, za duži odgovor i za foto-zadatke
- **isti pogrešan odgovor drugi put ne košta ništa** — objašnjenje se pamti

U **Podešavanja → Potrošnja AI poziva** vidiš tačno koliko je poziva otišlo i na šta.

## 4. Podešavanja, jedno po jedno

| Opcija | Šta radi |
|---|---|
| **Modeli** (brz / standardni / najjači / glas) | Koji se model zove za koji posao. Ostavi **Automatski** — aplikacija bira iz spiska koji vrati tvoj ključ i sama pređe na noviji kad ovaj bude penzionisan. Ručno biraš samo ako želiš baš određeni. Dugme *Osveži spisak modela* traži novu listu od Google-a. |
| **Agresivnost (1–5)** | Koliko strogo se meri da nešto „znaš". 1 = *može po nešto i da ne znam* (prag 70%, duži razmaci). 5 = *moram sve da znam* (prag 95%, sve se vrti češće). |
| **Pitanja po sesiji** | Koliko pitanja planira jedna sesija. |
| **Varijacija po pitanju** | Koliko puta se ista provera znanja postavi iz drugog ugla. 0 = bez varijacija. U jednoj sesiji vidiš najviše jednu iz grupe. |
| **Znakova gradiva po pozivu** | Veći broj = manje poziva, više tokena po pozivu. Ako ti model vraća odsečene odgovore, smanji ovo ili broj pitanja po pozivu. |
| **Zovi AI za objašnjenje** | Kad nema unapred napisanog objašnjenja. Isključi ako čuvaš kvotu. |
| **Neka sistem sam prilagođava strategiju** | Posle generisanja, model gleda tvoje rezultate i menja raspodelu tipova i težinu. |
| **Izgovor teksta** | *Browser* (besplatno, radi i na telefonu) · *Zvučnik računara* (Windows glasovi) · *Gemini glas* (prirodniji, troši kvotu). |
| **Tema** | Tamna ili svetla. |
| **Jezik pitanja** | Na kom jeziku model piše pitanja. Nezavisno od jezika aplikacije. |

## 5. Prvi predmet

**+ Novi predmet** (dole levo) → npr. `Matematika 2`.

Unutar njega **+ Podkategorija** → npr. `Kolokvijum 1`. Podkategorije idu u
nedogled: predmet → kolokvijum → oblast → lekcija, koliko god treba.

Učenje na nekom čvoru uvek obuhvata i sve ispod njega. Ako pokreneš sesiju na
`Matematika 2`, ispituje te iz svih kolokvijuma.

## 6. Materijali

Tab **Materijali** → prevuci fajlove ili klikni da izabereš.

Prima: PDF, Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`), slike, snimke
(audio i video), običan tekst, titlove (`.srt`, `.vtt`).

Posle upload-a svaki fajl dobije oznaku:

- **„pročitano lokalno"** i broj znakova — tekst je izvučen na tvom računaru,
  ništa nije poslato nigde
- **„ide AI-u"** — lokalno čitanje nije dalo upotrebljiv tekst (skeniran PDF,
  slika, snimak), pa se original šalje Gemini-ju kad kreneš da generišeš

Klikni **👁** da vidiš šta je tačno pročitano i koje je naslove našao. Ako je
tekst besmislen, klikni **⟳** da proba ponovo, ili isključi taj fajl.

> Stari binarni formati (`.doc`, `.xls`, `.ppt`) se ne čitaju. Otvori ih u Word-u
> i sačuvaj kao `.docx` ili PDF.

## 7. „Šta se tačno uči"

Tab **Pregled** → polje *Šta se tačno uči*.

Ovo je najvažnije polje u celoj aplikaciji. Ono ograničava obim, i ide u **svaki**
prompt.

Primeri:

```
Uči se samo do lekcije 5. Preskoči dokaze teorema.
```

```
Fokus na zadacima, ne na definicijama. Oznake koristi kao u skripti (Σ za sumu).
```

```
Poglavlja 3, 7 i 8. Tabele na kraju skripte su za referencu, ne za pitanja.
```

Uputstvo se **nasleđuje**: ono što napišeš na predmetu važi i za sve kolokvijume
ispod. Ispod polja vidiš celo uputstvo koje model stvarno dobija, sa nasleđenim
delom.

## 8. Generisanje pitanja

Tab **Generisanje**.

Na vrhu vidiš **plan pre nego što potrošiš išta**: koliko poziva, koliko znakova
gradiva, procena tokena, koliko pitanja se očekuje, i koji originalni fajlovi idu
AI-u.

Dole podesiš broj pitanja po pozivu, varijacije, model, i eventualno dodatno
uputstvo (*„više računskih zadataka, manje definicija"*).

**✨ Generiši preko Gemini-ja** — kreće posao; napredak vidiš u traci. Na kraju
dobiješ izveštaj: koliko je novih, koliko duplikata, i **šta je odbijeno i zašto**.

Odbijena pitanja nisu greška aplikacije — to je zaštita. Pitanje kome fali tačan
odgovor ili koje ima praznine bez oznaka ne ulazi u bazu polomljeno.

### Ako Gemini ne uspe

Ponekad model ne može da svari format, ili si potrošio kvotu. Tada:

1. **📤 Izvezi prompt za Claude** — dobiješ ceo tekst sa uputstvom
2. **📋 Kopiraj sve** i nalepi u Claude (ili bilo koji drugi model)
3. Kopiraj **ceo** odgovor modela
4. **📥 Nalepi odgovor** u aplikaciji

Nalepljeni odgovor prolazi kroz **potpuno istu proveru** kao Gemini-jev. Ako je
gradivo veliko, prompt je podeljen na delove — dugme *Sledeći deo →* te vodi kroz njih.

### Ispitna baza — pitanja tačno kako pišu

Ako fakultet deli **fiksnu listu pitanja** (npr. 100 pitanja, na ispitu dođe 20
od njih, doslovno), generisanje ti ne treba — treba ti da vežbaš **baš ta**
pitanja, bez AI prepričavanja. Za to je tab **Ispitna baza**.

1. Ubaci fajl sa pitanjima u *Materijali* (PDF, Word, tekst) — ili tekst samo
   nalepi u polje u tabu
2. **🔎 Prepoznaj pitanja** — vidiš spisak: koje pitanje, koliko odgovora, koji
   je označen kao tačan. **Ništa još nije upisano.**
3. **📥 Uvezi doslovno, bez AI** — pitanja i odgovori ulaze u bazu znak po znak
   iz dokumenta. Ne troši kvotu i radi bez ključa.

Prepoznaje se uobičajen format: numerisana pitanja (`1.`, `1)`, `Pitanje 1`),
odgovori `a) b) c)` ili crtice, tačan odgovor označen zvezdicom (`*b)` ili
`b) ... *`), redom `Tačan odgovor: b`, ili ključem na kraju (`Odgovori:` pa
`1. b`, `2. c`). Otvoreno pitanje sa `Odgovor: tekst` ispod postaje *kratak
odgovor*. Dugme *Koji format se prepoznaje?* u tabu pokazuje primer.

**Word i PDF ne čuvaju bold** kad se čitaju kao tekst. Ako je tačan odgovor
označen samo podebljanim slovima, dodaj zvezdice ili ključ na kraju — ili:

**🤖 AI prepiše doslovno** — za nesređene fajlove i skenove. Gemini prepisuje,
ali aplikacija **svako pitanje proverava u tekstu fajla**: ako tekst pitanja ili
neki odgovor nije nađen doslovno, pitanje se odbija i vidiš ga u izveštaju. Kad
dokument ne kaže koji je odgovor tačan pa ga model odredi sam, pitanje dobija
oznaku 🔍 *provera u fajlu* — da znaš šta da proveriš.

Uvezena pitanja u tabu *Pitanja* nose oznaku **ispit 1:1**. U tabu *Uči* se
pojavi kvadratić **„Samo ispitna pitanja"** — uključi ga kad hoćeš da vežbaš
samo njih. Redosled ponuđenih odgovora ostaje kao u dokumentu (podesivo pri
uvozu); kod AI-generisanih pitanja redosled se meša pri svakom prikazu.

## 9. Učenje

Tab **Uči** → podesiš način i pritisneš *Počni sesiju*.

**Načini:**
- *Pametno* — forsira ono što grešiš, savladano provlači povremeno
- *Samo slabe tačke* — od najslabijeg naviše
- *Samo novo* — pitanja koja još nisi video
- *Označena za proveru* — ono što si sam obeležio
- *Sve nasumično*

Uz svako pitanje imaš alatke:

| Dugme | Šta radi |
|---|---|
| 🔊 | Pročita pitanje naglas |
| 📝 **Beleška** | Tvoja beleška uz pitanje. Preživljava svaku izmenu pitanja. |
| 🚩 **Proveriti** | Označi da hoćeš ovo ponovo da pogledaš |
| 🔍 **Provera u fajlu** | Sumnjaš da se ponavlja ili da je AI pogrešio |
| 🗑 **Nebitno** | Za uklanjanje |
| ⏭ **Preskoči** | Ne sada — ali ostaje u igri, vratiće se |
| 🚫 **Zanemari zauvek** | Nikad me više ne pitaj ovo |

Posle odgovora dobijaš objašnjenje zašto je tačno tačno — i, kod netačnog, zašto
tvoj odgovor nije. Dole piše kada se pitanje sledeći put vraća.

Sve označeno kasnije nalaziš u tabu **Pitanja**, kroz filter po oznaci.

## 10. Učenje na telefonu

Server sluša na celoj mreži, pa telefon na **istom Wi-Fi-ju** može da ga otvori.

Adresu vidiš na **početnom ekranu aplikacije** (kartica *Otvori na telefonu*) i
u crnom prozoru pri pokretanju. Izgleda kao `http://192.168.1.12:8077`.

Ako je ponuđeno više adresa, probaj onu bez napomene — one označene kao
*VirtualBox*, *WSL* ili *VPN* skoro sigurno nisu tvoj Wi-Fi.

Ovo je ono što omogućava tip zadatka **„Uradi zadatak"**: rešiš na papiru, slikaš
telefonom, i AI proverava postupak.

> Ako telefon ne može da otvori stranicu, najčešće je kriv Windows firewall.
> Pri prvom pokretanju iskoči prozor *„Allow access"* — mora se dozvoliti za
> **privatne mreže**. Ako si to slučajno odbio: *Windows Security → Firewall &
> network protection → Allow an app through firewall* → pronađi Python i čekiraj
> *Private*.

## 11. Strategija i dopune

Tab **Strategija** pokazuje kako te sistem trenutno ispituje i **zašto** —
raspodelu tipova, teme u fokusu, i greške koje ponavljaš.

*🔄 Neka AI predloži novu strategiju* pošalje modelu tvoje rezultate i dobije novu
verziju. Svaka verzija se čuva sa obrazloženjem i **vraća jednim klikom**.

> Menja se samo ono što je u bazi — kod aplikacije se ne dira nikad.

Tab **Dopune**: kad se u učenju vidi rupa koja se ponavlja, AI ti napiše kratku
dopunu baš za te tačke. Originalni materijali se ne diraju.

## 12. Ažuriranje

**Podešavanja → Verzija i ažuriranje → Preuzmi i ažuriraj.**

Aplikacija sama proveri ima li novije verzije. Ako ima, preuzme je odmah — ali
je **ugradi tek pri sledećem pokretanju**. Razlog je prozaičan: dok radi,
aplikacija drži svoje fajlove otvorene i ne može da ih prepiše ispod sebe.

Znači, tri koraka: klikni *Preuzmi*, zatvori crni prozor, pokreni ponovo.
Pri pokretanju piše `Ugradjujem novu verziju...` i to je gotovo za sekundu.

> Tvoja pitanja, materijali i napredak se **ne diraju**. Ažurira se samo kod
> aplikacije. Folder `data/` ne dodiruje ni instalacija ni ažuriranje.

Ako se predomisliš pre restarta, dugme *Odustani* obriše preuzeto.

## 13. Bekap

Sve tvoje je u folderu **`data/`**:

- `data/skripta.db` — pitanja, odgovori, napredak, podešavanja
- `data/materials/` — tvoji fajlovi u originalu

Bekap = kopiraj taj folder. Vraćanje = vrati ga nazad. Prenos na drugi računar =
prekopiraj i njega i celu aplikaciju.

## 14. Kad nešto ne radi

| Simptom | Šta je |
|---|---|
| `START.bat` se otvori i odmah zatvori | Python nije u PATH-u. Reinstaliraj sa čekiranim *Add python.exe to PATH*. |
| Browser kaže da stranica ne postoji | Server nije podignut — pogledaj crni prozor, tu piše greška. |
| „Nije unet Gemini API ključ" | Podešavanja → unesi ključ i pritisni *Proveri i sačuvaj*. |
| „API ključ nije prihvaćen" / „Ključ nema pravo pristupa" | Verovatno stari *standard* ključ. Napravi novi na <https://aistudio.google.com/api-keys> — vidi poglavlje 3. |
| „Traženi model ne postoji za ovaj ključ" | Model je penzionisan. Podešavanja → *Osveži spisak modela*. Aplikacija to i sama pokuša pri prvom takvom pozivu. |
| „Prešao si besplatnu kvotu" | Sačekaj minut-dva. Ili spusti model na *brz i jeftin*. |
| Model vraća odsečene odgovore | Smanji *Pitanja po pozivu* ili *Znakova gradiva po pozivu*. |
| PDF je „ide AI-u", a ima tekst | Skeniran je, ili koristi font bez mape znakova. Aplikacija to prepoznaje i šalje original — radi, samo troši više kvote. |
| Telefon ne može da otvori | Firewall (vidi poglavlje 10), ili telefon nije na istom Wi-Fi-ju. |
| Nema srpskog glasa | Windows: *Settings → Time & Language → Speech → Add voices*. Ili prebaci izgovor na *Gemini glas*. |
| U crnom prozoru piše `ConnectionResetError ... forcibly closed by the remote host` | Telefon ili browser je prekinuo vezu (zaključan ekran, zatvoren tab). Nije greška — novije verzije to više ni ne ispisuju. |
| Pitanje je pola latinicom, pola ćirilicom | Model nije poslušao uputstvo. Nova pitanja se sada uvek upisuju u jednom pismu; za stara pritisni *Podešavanja → Ujednači pismo u postojećim pitanjima*. |
| Tačan odgovor je „uvek prvi ponuđeni" | Bilo je tako u starijoj verziji; sada se redosled ponuđenih meša pri svakom prikazu. Za doslovno uvezena ispitna pitanja redosled ostaje kao u dokumentu, osim ako pri uvozu ne isključiš tu opciju. |
| Ažurirao sam, a ništa se nije promenilo | Nisi ponovo pokrenuo aplikaciju. Zatvori crni prozor i klikni ikonicu opet. |
| „Windows protected your PC" pri instalaciji | Normalno za `.bat` sa interneta. *More info* → *Run anyway*. |
| Hoću nešto što aplikacija ne ume | Tab **Predlozi** — vidi [predlozi/README.md](../predlozi/README.md). |
