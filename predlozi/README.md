# Predlozi za nadogradnju

Ovaj folder postoji zbog jednog scenarija:

> Skinuo si `skripta-faks` kao osnovni template. Radi, koristiš ga sa besplatnim
> Gemini ključem. Posle nekog vremena ti nešto zasmeta — fali ti tip zadatka,
> smeta ti kako izgleda ekran, hoćeš da ti čita pitanja drugačije. Ne umeš (ili
> nemaš vremena) da to sam napišeš.
>
> Onda otvoriš plaćenog AI asistenta, i tu nastaje problem: on ne zna ovu
> aplikaciju. Ako mu samo kažeš „dodaj mi ovo", počeće da nagađa — izmisliće
> fajlove, dodaće biblioteku koju ovaj projekat namerno nema, i polomiti nešto
> treće.
>
> Ovaj folder je tu da mu **daš mapu i tačan nalog**, umesto da nagađa.

## Šta je gde

| Fajl | Šta je |
|---|---|
| `KONTEKST-ZA-AI.md` | Mapa celog projekta: svaki fajl, sve rute, sve tabele, i pravila koja se ne smeju prekršiti. **Generisana iz koda** — ne piše se rukom. |
| `SABLON-ZAHTEVA.md` | Šablon po kome pišeš šta hoćeš, da ne zaboraviš ono što je bitno. |
| `predlog-NNNN-*.md` | Gotovi predlozi. Svaki na kraju ima blok „Nalog za AI asistenta" koji doslovno kopiraš. |

## Tok, korak po korak

**1. Opiši šta ti fali — svojim rečima.**

U aplikaciji: **Predlozi** (u levoj koloni) → *Novi predlog*. Piši kao čoveku:
*„Kad učim formule, hoću da mogu da ih napišem rukom na papiru i slikam, ali za
hemiju — sad to radi samo za matematiku."*

Ne moraš da znaš kako se to rešava. To je posao sledećeg koraka.

**2. Gemini to prevodi u nalog.**

Aplikacija mu šalje mapu projekta, tvoj zahtev, i kratak profil kako koristiš
aplikaciju. Dobija se `predlog-NNNN-*.md` u ovom folderu: šta je razumeo, koji
fajlovi se diraju, šta ne sme da se pokvari, i šta treba da razjasniš pre nego
što neko krene.

Ako zahtev ne može da se uradi bez kršenja pravila projekta (npr. traži spoljnu
biblioteku), predlog to piše na vrhu, umesto da ćutke predloži nešto što će
pokvariti aplikaciju.

**3. Odneseš nalog plaćenom asistentu.**

Otvoriš asistenta **u folderu aplikacije** i daš mu dve stvari:

- `predlozi/KONTEKST-ZA-AI.md` (mapa — priložiš je kao fajl ili nalepiš)
- blok „Nalog za AI asistenta" sa dna predloga

Prvi mu govori gde šta stoji i šta sme; drugi šta tačno da uradi.

**4. Pregledaš i commit-uješ.**

Kad asistent završi, pokreni testove:

```
python run_tests.py
```

Ako je zeleno i aplikacija radi — commit. Ako nije, vrati se asistentu sa tekstom
greške; on sad ima i mapu i nalog, pa ima od čega da krene.

## Zašto je ovo u gitu, a `data/` nije

`data/` su tvoji podaci — skripte, pitanja, napredak. To je tvoje i ne ide nigde.

`predlozi/` su polazna tačka izmene koda. Ako neko forkuje ovu aplikaciju, korisno
mu je da vidi šta je već traženo i šta je od toga urađeno — isto kao istorija
commit-ova.

## Ako mapa zastari

`KONTEKST-ZA-AI.md` se generiše iz stvarnog koda. Posle svake veće izmene:

```
python mapa.py
```

pa commit-uj rezultat. Ista dugmad postoji i u aplikaciji (**Predlozi → Osveži mapu**).

Mapa koja laže je gora od nikakve mape: asistent koji je čita menjaće fajlove
kojih više nema.

## Šta aplikacija NIKAD ne radi

**Ne primenjuje predloge.** Piše ih, i tu joj se posao završava. Kod menjaš ti,
kroz git, sa nečim što ume da testira šta je napisalo.

To je svesna odluka: neproverena izmena koda koja se sama primenjuje obara server
usred učenja, a uzrok tražiš u kodu koji nisi pisao.
