# Rodinné kino pro Kodi

České filmové prostředí pro Kodi s nabídkami Domů, Filmy, Seriály, Moje a Streamovací služby. Hledá podle názvu, herce a roku, umí procházet žánry, postupně doplňuje seznamy a otevírá filmy, řady a díly ve stejném okně. Na plakátech ukazuje zhlédnutí a průběh přehrávání z Traktu. Při výběru zdrojů dává přednost českému zvuku a 1080p. Hodnocení ČSFD z Atlasu je volitelné.

## Instalace

Pro **Kodi 21 Omega** stačí stáhnout jeden ZIP. Při prvním spuštění instalátor obstará Arctic Fuse 3 a jeho závislosti, Webshare – YAWSP, Trakt a češtinu. Poté aktivuje vzhled a připraví nabídky, vzhled karet, hledání, postupné načítání, ovládání Zpět a přehrávač podle domácí sestavy na Homaticsu. Instalace potřebuje internet.

1. Stáhni [kompletní instalační ZIP Rodinného kina 1.8.1](https://raw.githubusercontent.com/Bbambaaamm/rodinne-kino-kodi/main/dist/script.michal.family.repair/script.michal.family.repair-1.8.1.zip). V Kodi dej **Doplňky → Instalovat ze souboru ZIP** a vyber stažený soubor. Pro ruční instalaci ZIP povol **Neznámé zdroje**.
2. Otevři **Programové doplňky → Rodinné kino – instalace a servis** a potvrď instalaci. Kodi může vyžádat potvrzení instalace jednotlivých součástí a přepnutí na Arctic Fuse 3. Instalační postup uloží místní zálohu nastavení a své změny zaznamená pro obnovu. Pro aktuální závislosti vzhledu povolí aktualizace z libovolného repozitáře. Automatické dotazy Traktu na hodnocení vypne stejně jako v domácí sestavě.
3. Přihlas své účty v **Moje → Servis → Otevřít přihlášení Webshare** a **Otevřít přihlášení Trakt**. Trakt připoj také v nastavení **Doplňky → Programové doplňky → Trakt**, aby se zaznamenávalo přehrávání. U nového TMDb Helperu instalátor doplní samostatnou integraci Trakt.
4. V **Moje → Servis → Kontrola rodinného kina** ověř sestavu. ČSFD lze zapnout pod **Hodnocení ČSFD – Atlas** s vlastním klíčem a tarifem podporujícím ČSFD.

Na sestavě s vlastními úpravami Arctic Fuse 3 nejdřív uvolni vlastní nabídku na pozici 4, kterou použijí Streamovací služby. Při přerušeném stahování nebo odmítnutí systémového potvrzení lze instalátor znovu spustit. Již připravené součásti zkontroluje a pokračuje. Obnovu původního nastavení najdeš ve stejném servisním menu.

Instalátor rozšiřuje instalaci vzhledu z původního balíčku `michal-kodi-one-click-setup-1.0.2.zip` o aktuální Rodinné kino. Přibalený filmový doplněk má verzi **0.9.15**. Součásti třetích stran získává z [repozitáře autora Arctic Fuse](https://github.com/jurialmunkey/repository.jurialmunkey), [oficiálního repozitáře Kodi](https://kodi.tv/addons/omega/) a [zdroje Webshare – YAWSP](https://github.com/Webshare/Web). U přímo stahovaných ZIPů kontroluje otisk SHA-256. Instalační ZIP obsahuje i vlastní repozitář pro další aktualizace a přidá ho při první instalaci.

Instalaci přímo z internetu přidáš přes **Nastavení → Správce souborů → Přidat zdroj** s adresou **https://bbambaaamm.github.io/rodinne-kino-kodi/** a názvem **Rodinné kino**. V **Doplňky → Instalovat ze souboru ZIP → Rodinné kino** vyber **repository.rodinne.kino-1.0.0.zip**, potom pokračuj přes **Instalovat z repozitáře → Rodinné kino → Programové doplňky**. Lze také stáhnout [samostatný ZIP repozitáře](https://bbambaaamm.github.io/rodinne-kino-kodi/repository.rodinne.kino-1.0.0.zip).

## Automatické aktualizace

Instalátor zapne v Kodi automatické aktualizace doplňků. Po stažení nové verze z repozitáře služba sama aktualizuje filmový doplněk, naše soubory vzhledu, nabídky, přehrávač a ovládání. Čeká na zavřené přehrávání i karty titulů a nejméně 15 sekund nečinnosti v hlavní nabídce nebo v některé z našich sekcí. Pozastavené video také odloží použití změn.

Před použitím změn se uloží místní záloha právě fungující sestavy. Při chybě se obnoví předchozí soubory a nastavení a služba pokus zopakuje s časovým odstupem. Dokončená verze se zaznamená až po dokončení celého postupu. Původní záloha před první instalací zůstává dostupná přes servisní menu.

Služba pozná i změnu verze Arctic Fuse 3 a znovu na ni použije naše úpravy. Při nečinnosti kontroluje také soubory hledání, hodnocení, průběhu a šablon služeb, které může aktualizace vzhledu obnovit do výchozí podoby.

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

Původní kód Rodinného kina je pod licencí MIT. Arctic Fuse 3 je dílo [jurialmunkey](https://github.com/jurialmunkey/skin.arctic.fuse.3) pod licencí [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Instalátor přidává úpravy do místně nainstalovaného vzhledu a jeho vlastní soubory zůstávají pod původní licencí. Webshare, Trakt a další služby spravují jejich provozovatelé.
