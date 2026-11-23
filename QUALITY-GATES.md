# Brána kvality Rodinného kina

Každá změna musí před sloučením projít kontrolou **Quality Gates** v GitHub Actions. Červený výsledek znamená, že se změna nesmí vydat. Veřejné vydání navíc vždy vyžaduje výslovné schválení uživatele.

## Povinné funkce

- Každá obsahová sekce zobrazuje pouze titul s potvrzeným videem na Webshare.
- Film se páruje podle názvu a roku. Epizoda podle identity seriálu a přesného `SxxEyy`.
- Domů, Filmy, Seriály, žánry, streamovací služby, osobní seznamy, historie a hledání používají stejné pravidlo dostupnosti.
- Zpět zachová správnou obrazovku a výběr. Automatické stránkování začíná 20 položkami a přidává dalších 20.
- Pád, zamrznutí, ztráta výběru nebo nesprávné video mají nulovou toleranci.

## Rozpočty odezvy

| Operace | Cíl | Nepřijatelná mez |
|---|---:|---:|
| Pohyb výběru ovladačem | 100 ms | 200 ms |
| Zpět a obnovení výběru | 300 ms | 700 ms |
| Již načtená sekce | 0,5 s | 1 s |
| První použitelné karty ze sítě (milník 20) | 3 s | 6 s |
| První nové karty další dávky (milník +20) | 2 s | 4 s |
| Hledání | 3 s | 6 s |
| Karta z cache / ze sítě | 0,5 s / 1,5 s | 1 s / 3 s |
| Nabídka zdrojů | 3 s | 6 s |
| Zahájení přehrávání | 5 s | 10 s |
| Viditelná odezva na delší práci | 100 ms | 200 ms |

Překročení cíle je varování a požaduje kontrolu trendu. Překročení nepřijatelné meze blokuje vydání.
Milník určuje výsledný počet karet. Při pomalejším Webshare se pouze potvrzené karty
zobrazují postupně v krátkých dávkách, takže uživatel nečeká na dokončení celé dvacítky.

## Co kontroluje GitHub

1. Všechny automatické testy na Windows i Linuxu.
2. Přesné párování titulů, roku, řady a dílu.
3. Dostupnost na Webshare ve všech typech seznamů a hledání.
4. Parametry stránkování, počet souběžných požadavků a zachování posledních tří verzí.
5. Sestavení instalačního ZIPu a neporušenost repozitáře.
6. Technický protokol z Homaticsu svázaný kontrolními součty se stejnými zdrojovými soubory.

GitHub-hostovaný běh nemá přístup do domácí sítě. Skutečné síťové latence, ovladač, návrat, obraz a zvuk proto měří Homatics před vydáním. Výsledek se uloží do `quality/device-latest.json`; kontrola odmítne protokol patřící k jiné verzi souborů.

Pro úplné vynucení nastav v GitHubu pravidlo větve `main` a jako povinné kontroly zvol `Functional tests` a `Quality contract`.

