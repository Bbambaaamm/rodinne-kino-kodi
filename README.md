# Rodinné kino pro Kodi

České filmové prostředí pro Kodi s nabídkami Domů, Filmy, Seriály, Moje a Streamovací služby. Hledá podle názvu, herce a roku, umí procházet žánry, postupně doplňuje seznamy a otevírá filmy, řady a díly ve stejném okně. Na plakátech ukazuje zhlédnutí a průběh přehrávání z Traktu. Při výběru zdrojů dává přednost českému zvuku a 1080p. Hodnocení ČSFD z Atlasu je volitelné.

## Instalace

Pro **Kodi 21 Omega** stačí stáhnout jeden ZIP. Při prvním spuštění instalátor obstará Arctic Fuse 3 a jeho závislosti, Webshare – YAWSP, Trakt a češtinu. Poté aktivuje vzhled a připraví nabídky, vzhled karet, hledání, postupné načítání, ovládání Zpět a přehrávač podle domácí sestavy na Homaticsu. Instalace potřebuje internet.

1. Stáhni [kompletní instalační ZIP Rodinného kina 1.8.13](https://raw.githubusercontent.com/Bbambaaamm/rodinne-kino-kodi/main/dist/script.michal.family.repair/script.michal.family.repair-1.8.13.zip). V Kodi dej **Doplňky → Instalovat ze souboru ZIP** a vyber stažený soubor. Pro ruční instalaci ZIP povol **Neznámé zdroje**.
2. Otevři **Programové doplňky → Rodinné kino – instalace a servis** a potvrď instalaci. Kodi může vyžádat potvrzení instalace jednotlivých součástí a přepnutí na Arctic Fuse 3. Instalační postup uloží místní zálohu nastavení a své změny zaznamená pro obnovu. Pro aktuální závislosti vzhledu povolí aktualizace z libovolného repozitáře. Automatické dotazy Traktu na hodnocení vypne stejně jako v domácí sestavě.
3. Instalace otevře průvodce **Dokončení Rodinného kina** s připojením Webshare, osobních seznamů Traktu a ukládání zhlédnutí. U Webshare zadej jméno a heslo, u Traktu potvrď propojení podle zobrazených pokynů. Webshare otevře dva kroky s jasnými českými popisky pro jméno nebo e-mail a pro heslo. Přihlášení se uloží až po úspěšném ověření účtu. Průvodce lze znovu otevřít v **Moje → Servis → Dokončit přihlášení účtů**. U nového TMDb Helperu instalátor doplní samostatnou integraci Trakt.
4. V **Moje → Servis → Kontrola rodinného kina** ověř sestavu. ČSFD lze zapnout pod **Hodnocení ČSFD – Atlas** s vlastním klíčem a tarifem podporujícím ČSFD.

Na sestavě s vlastními úpravami Arctic Fuse 3 nejdřív uvolni vlastní nabídku na pozici 4, kterou použijí Streamovací služby. Při přerušeném stahování nebo odmítnutí systémového potvrzení lze instalátor znovu spustit. Již připravené součásti zkontroluje a pokračuje. Obnovu původního nastavení najdeš ve stejném servisním menu.

Instalátor rozšiřuje instalaci vzhledu z původního balíčku `michal-kodi-one-click-setup-1.0.2.zip` o aktuální Rodinné kino. Přibalený filmový doplněk má verzi **0.9.18**. Součásti třetích stran získává z [repozitáře autora Arctic Fuse](https://github.com/jurialmunkey/repository.jurialmunkey), [oficiálního repozitáře Kodi](https://kodi.tv/addons/omega/) a [zdroje Webshare – YAWSP](https://github.com/Webshare/Web). U přímo stahovaných ZIPů kontroluje otisk SHA-256. Instalační ZIP obsahuje i vlastní repozitář pro další aktualizace a přidá ho při první instalaci.

Instalaci přímo z internetu přidáš přes **Nastavení → Správce souborů → Přidat zdroj** s adresou **https://bbambaaamm.github.io/rodinne-kino-kodi/** a názvem **Rodinné kino**. V **Doplňky → Instalovat ze souboru ZIP → Rodinné kino** vyber **repository.rodinne.kino-1.0.0.zip**, potom pokračuj přes **Instalovat z repozitáře → Rodinné kino → Programové doplňky**. Lze také stáhnout [samostatný ZIP repozitáře](https://bbambaaamm.github.io/rodinne-kino-kodi/repository.rodinne.kino-1.0.0.zip).

## Aktivní výběr v potvrzení vzhledu 1.8.13

Na Homaticsu Box R 4K Plus s Kodi 21.2 se při změně z instalátoru zobrazilo potvrzovací okno bez aktivního výběru. Stejná změna přes Nastavení měla aktivní výběr a ovladačem fungovala. Výslovné předání výběru na nativní tlačítko „Ne“ obnovilo přepínání šipkami také v zaseknutém okně.

Instalátor nyní při otevření svého potvrzení ověří aktivní výběr. Chybí-li, jednou jej předá na „Ne“. Již zvolené tlačítko zachová a při překrytí jiným dialogem počká. Výsledek dál potvrzuje uživatel; Zpět ani časový limit se nepočítají jako souhlas. Ověření celého nového balíčku na zařízení zatím probíhá.

## Navigace v potvrzení vzhledu 1.8.12

Tlačítka potvrzení používají samostatnou skupinu s výslovnými přechody pro všechny čtyři šipky. Původní seznam tlačítek při vytváření přepisoval svislé přechody svých potomků; nová skupina je zachovává. Aktualizuje se také dřívější úprava z 1.8.10 a 1.8.11. Potvrzení zůstává na uživateli a Zpět nebo vypršení systémové lhůty vrací původní vzhled.

Na Homaticsu Box R 4K Plus s Kodi 21.2 byla chyba 1.8.11 reprodukována i síťovými šipkami. Samotná změna skupiny ve verzi 1.8.12 chybějící aktivní výběr při instalaci nevyřešila; tuto část řeší 1.8.13.

## Kompatibilita s Arctic Fuse 3.5.7 v 1.8.11

Nový vzhled používá samostatné generované řádky hodnocení pro filmy, seriály a epizody. Instalátor podporuje tento formát i starší společný řádek a přidává ČSFD bez nahrazení ostatních hodnocení. U katalogů streamovacích služeb zachovává nové pravidlo viditelnosti sekce a další obsah původního widgetu. Neznámou strukturu nadále odmítne před zápisem.

Vydání zahrnuje opravu potvrzení vzhledu z 1.8.10. Prošlo 89 kontrol; úpravy hodnocení, streamovacích šablon a průběhu přehrávání byly navíc ověřeny proti aktuálním zdrojovým souborům Arctic Fuse.

## Potvrzení vzhledu ovladačem a dotykem 1.8.10

Instalátor připraví potvrzovací dialog Arctic Fuse ještě před přepnutím vzhledu. Volby používají přímo standardní tlačítka Kodi pro Ano, Ne a případnou třetí volbu, místo přesměrování přes skryté ovládací prvky. Viditelný výběr má výrazné podsvícení, každé tlačítko vysokou dotykovou plochu a přepínání všemi čtyřmi šipkami. Potvrzení zůstává na uživateli; OK, Zpět i časový návrat používají standardní chování Kodi.

Instalace sleduje i potvrzení překryté průběhem načítání. S nabídkami pokračuje až po potvrzení vzhledu a dvou sekundách ustáleného stavu. Vlastní průvodce vzhledu neotevírá souběžně. Původní soubor ukládá do místní zálohy a úpravu obnoví také po aktualizaci vzhledu.

Prošlo 83 kontrol včetně odmítnutí a chybějícího potvrzení, překrývajícího dialogu, nativních tlačítek, navigace a opakovaného použití změny.

## Automatické aktualizace

Instalátor zapne v Kodi automatické aktualizace doplňků. Po stažení nové verze z repozitáře služba sama aktualizuje filmový doplněk, naše soubory vzhledu, nabídky, přehrávač a ovládání. Čeká na zavřené přehrávání i karty titulů a nejméně 15 sekund nečinnosti v hlavní nabídce nebo v některé z našich sekcí. Pozastavené video také odloží použití změn.

Před použitím změn se uloží místní záloha právě fungující sestavy. Při chybě se obnoví předchozí soubory a nastavení a služba pokus zopakuje s časovým odstupem. Dokončená verze se zaznamená až po dokončení celého postupu. Původní záloha před první instalací zůstává dostupná přes servisní menu.

Služba pozná i změnu verze Arctic Fuse 3 a znovu na ni použije naše úpravy. Při nečinnosti kontroluje také soubory hledání, hodnocení, průběhu a šablon služeb, které může aktualizace vzhledu obnovit do výchozí podoby.

## Návrat k předchozí verzi

Repozitář nabízí aktuální vydání a dvě předchozí verze instalačního doplňku. Například u 1.8.5 jsou dostupné také 1.8.4 a 1.8.3. Stejné tři původní ZIPy jsou ke stažení na instalační stránce. Při každém sestavení se výběr verzí obnoví automaticky.

V Kodi otevři **Rodinné kino – instalace a servis → Informace → Verze** a vyber předchozí vydání. Pak nech Kodi chvíli bez přehrávání na **Domů**, aby služba použila soubory a nastavení vybrané verze včetně přibaleného filmového doplňku. Účty se zachovají. Kodi 21 při volbě starší verze z repozitáře automaticky připne tuto verzi proti automatické aktualizaci; návrat na nejnovější vydání proveď stejnou nabídkou Verze.

## Přednačítání plakátů 1.8.9

Při zaměření dlaždice streamovací služby doplněk v pozadí připraví první čtyři plakáty jejího filmového katalogu. Po otevření služby je použije z místní cache. Stahování je omezené velikostí souboru i časem; při změně zaměřené služby se předchozí práce přeruší. Následující položky a obrázky mimo tento katalog fungují jako dosud.

## Obnova přihlášení Webshare 1.8.8

Při přehrávání doplněk ověří odpověď Webshare. Když uložený token přestane platit, použije lokálně uložené přihlašovací údaje YAWsP, obnoví token a jednou zopakuje požadavek na film. Údaje ani odkaz na video se nezapisují do logu. Pokud účet nemá uložené heslo nebo server odmítne přihlášení, zdroj zůstane nedostupný.

## Dotyk na tabletu Lenovo 1.8.7

Na YT3-X90F jsou ověřené dotykové plochy celé horní nabídky včetně Moje a ozubeného kolečka, volba kategorií jako Chci vidět a viditelné tlačítko Zpět v hlavním nastavení. Oprava se po aktualizaci vzhledu znovu použije.

Svislé přejetí z dolní hrany zachytává Android a vzhled Arctic Fuse 3 se svým vodorovným řádkem filmů zatím neposouvá jako běžná mobilní stránka. Zkušební změna režimu vzhledu a zmenšení rozhraní zhoršily zobrazení karet, proto nebyly zahrnuty.

## Spolehlivé přihlášení Webshare 1.8.6

Průvodce po instalaci i servisní volba **Otevřít přihlášení Webshare** nyní používají dvě standardní klávesnice Kodi s přímo zadanými českými nadpisy. Přihlášení se tak nespoléhá na načtení překladů nastavení YAWsP a nevyžaduje přepnutí jazyka ani restart. Heslo je při zadávání skryté a dříve uložené heslo se do klávesnice nepředvyplňuje.

Zpět nebo prázdné pole ukončí zadávání bez síťového přihlášení. Zrušené nebo odmítnuté přihlášení zachová původní účet. Jméno, heslo a token se uloží do místního YAWsP až po úspěšném ověření; do instalačního balíčku ani zprávy o instalaci se nedostanou. Automatické dokončení z dříve zadaných místních údajů zůstává zachované.

Prošlo 70 kontrol, včetně zrušení obou kroků, prázdných vstupů, skrytého hesla, zachování účtu při chybě a stejného přihlášení ze servisní nabídky.

## Dokončení instalace se starším vzhledem 1.8.5

Před nastavením nabídek instalátor ověří Arctic Fuse 3 alespoň 3.5.4. U staršího vzhledu obnoví katalogy repozitářů a počká na aktualizaci. Pokud kompatibilní verzi nelze získat, vysvětlí postup aktualizace a nepokračuje do úprav nabídek. Tím řeší stav, kdy je již nainstalovaný balíček Rodinného kina, ale hledání a služby se kvůli starému vzhledu nepodařilo nastavit.

Prošlo 65 kontrol instalátoru, souborů vzhledu a sestavení balíčku. Nové kontroly zahrnují aktualizaci starého vzhledu, ukončení při nedostupné aktualizaci, řazení vydání podle čísel verzí, kontrolu metadat archivů a zachování původních ZIPů při jejich zpřístupnění pro návrat.

## Účty a dostupnost

- Katalogy služeb ukazují nabídku pro ČR z dat TMDb a JustWatch. Pro přehrávání z Webshare se používá vlastní účet a soubory, ke kterým máš přístup. Karty služeb slouží k procházení katalogů.
- Přihlašovací údaje, klíče, historie a zálohy jsou uložené v instalaci uživatele. Zálohu lze obnovit v servisním menu, dokud je aktivní Arctic Fuse 3.
- Nastavení reprosoustavy, zvukového výstupu a projektoru patří ke konkrétnímu zařízení a nastavuje se v Kodi samostatně.
- Přihlašování probíhá přímo v Kodi. Osobní nabídky se naplní po připojení vlastního Traktu a přehrávání Webshare po vlastním přihlášení.

## Sestavení ze zdrojů

Spusť `python build.py`. Skript sestaví instalační ZIP, ZIP repozitáře a index pro Kodi v `dist/`. U obou ZIPů je kontrolní součet SHA-256. Filmový doplněk je ve `addons/plugin.video.webshare.available` a instalátor v `addons/script.michal.family.repair`.

## Ověření verze 1.8.1

Prošlo 162 stávajících kontrol filmového doplňku a 34 kontrol instalátoru a automatických aktualizací. Kontroly zahrnují odložení za přehrávání, opakování po chybě, obnovu předchozích souborů, Windows cesty delší než 260 znaků a pozdní potvrzení změny vzhledu. Obsah ZIPu, kontrolní součty a veřejné stažení jsou kontrolované při zveřejnění.

V odděleném Kodi 21.3 na PC byla dokončena výchozí instalace 1.8.0 s Arctic Fuse 3 verze 3.5.4 a filmovým doplňkem 0.9.14. Při nativní kontrole veřejného repozitáře Kodi automaticky stáhlo 1.8.1. Za pozastaveného místního testovacího videa zůstaly úpravy čekat. Po ukončení videa se samy použily soubory vzhledu 1.8.1 a filmový doplněk 0.9.15.

Byla ověřena shoda všech 30 souborů filmového doplňku, osmi definic nabídek a okna hledání s vydaným balíčkem. Po restartu Kodi služba opět běžela a již dokončená sestava se znovu nepoužila. Osobní seznamy a přehrávání Webshare používají vlastní účty připojené v cílovém Kodi.

## Oprava zálohování 1.8.2

Zálohování, úpravy vzhledu a obnova kopírují obsah souborů bez přenosu časů a oprávnění. Tím se odstraňuje chyba `Permission denied` při nastavování vlastností zálohovaných složek na sdíleném úložišti Androidu. Skutečné odmítnutí čtení nebo zápisu dál instalaci zastaví a neoznačí neúplnou zálohu za hotovou.

Prošlo 40 kontrol instalátoru. Šest kontrol pokrývá prázdnou složku `keymaps`, vnořené soubory, zachování původní zálohy, opakování po skutečném odmítnutí zápisu a obnovu předchozího obsahu včetně automatických aktualizací. Omezení zápisu vlastností byla při kontrolách simulována; dokončení instalace na konkrétní televizi je nutné ověřit po aktualizaci.

Pokud se instalace zastavila při zálohování, v Kodi vyhledej aktualizace repozitáře Rodinné kino, aktualizuj doplněk **Rodinné kino – instalace a servis** alespoň na 1.8.2 a znovu jej spusť. Nainstalované součásti zůstanou zachované a instalační postup je zkontroluje. Data Kodi není potřeba mazat.

## Dokončení nastavení 1.8.3

Instalátor nyní přímo nastaví i uzly nabídek Filmy, Seriály a Moje, které má čistý Arctic Fuse 3 ve výchozím stavu vypnuté. Samotné starší nastavení jejich názvů a přepínačů v novém vzhledu nestačilo.

Po použití vzhledu následuje průvodce účty. Již přihlášené účty zachová a případné uložené údaje Webshare použije k dokončení přihlášení. Při aktualizaci dřívější neúplné sestavy nabídne průvodce jednou při nečinnosti v nabídce. Dokončení lze odložit; neúplné přihlášení nebude označeno jako hotové. Osobní údaje a tokeny zůstávají v příslušných místních doplňcích.

Chybějící účet zobrazí v seznamu přímo tlačítko **Připojit Trakt** nebo **Připojit Webshare**. Po přihlášení se znovu vyžádá načtení osobních seznamů. Prošlo 54 kontrol instalátoru včetně navigace, zachování již nastavených účtů, odložení průvodce a přihlašovacího postupu Webshare se simulovanými odpověďmi.

V odděleném Kodi 21.3 na PC se 1.8.3 stáhla z veřejného repozitáře a sama použila na dosavadní sestavu 1.8.1. Ověřeny byly zapnuté uzly Filmy, Seriály, Moje a Streamovací služby a shoda všech 30 souborů filmového doplňku s vydaným balíčkem. Webshare se úspěšně přihlásilo pomocí místně uložených údajů. Průvodce správně rozlišil již připojené ukládání zhlédnutí a chybějící připojení osobních seznamů Traktu. Katalog filmového žánru i katalog seriálů služby vrátily po deseti titulech bez chyby. Osobní seznamy lze ověřit až po potvrzení připojení jejich účtu uživatelem.

## Dotyk a hesla v Kodi 1.8.4

Na Androidu instalátor přidává dotykové cíle do aktivních obrazovek horní nabídky Arctic Fuse 3. V klávesnici vzhledu doplní standardní tlačítko Kodi pro zobrazení a skrytí zadávaného hesla. Úpravy se po aktualizaci vzhledu obnoví při nečinnosti, bez zásahu do přihlašovacích údajů. Při změně struktury vzhledu se úprava zastaví a nahlásí chybu místo zápisu neplatného XML.

Tato úprava řeší ovládací prvky vzhledu. Pokud dotykový ovladač tabletu sám generuje nechtěné stisky mimo Kodi, je třeba vyřešit také tento problém zařízení.

Původní kód Rodinného kina je pod licencí MIT. Arctic Fuse 3 je dílo [jurialmunkey](https://github.com/jurialmunkey/skin.arctic.fuse.3) pod licencí [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Instalátor přidává úpravy do místně nainstalovaného vzhledu a jeho vlastní soubory zůstávají pod původní licencí. Webshare, Trakt a další služby spravují jejich provozovatelé.
