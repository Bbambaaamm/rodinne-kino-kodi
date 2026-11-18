# Rodinné kino pro Kodi

České filmové prostředí pro Kodi s nabídkami Domů, Filmy, Seriály, Moje a Streamovací služby. Hledá podle názvu, herce a roku, umí procházet žánry, postupně doplňuje seznamy a otevírá filmy, řady a díly ve stejném okně. Na plakátech ukazuje zhlédnutí a průběh přehrávání z Traktu. Při výběru zdrojů dává přednost českému zvuku a 1080p. Hodnocení ČSFD z Atlasu je volitelné.

## Instalace

Pro **Kodi 21 Omega** stačí stáhnout jeden ZIP. Při prvním spuštění instalátor obstará Arctic Fuse 3 a jeho závislosti, Webshare – YAWSP, Trakt a češtinu. Poté aktivuje vzhled a připraví nabídky, vzhled karet, hledání, postupné načítání, ovládání Zpět a přehrávač podle domácí sestavy na Homaticsu. Instalace potřebuje internet.

1. Stáhni [kompletní instalační ZIP Rodinného kina 1.7.0](https://raw.githubusercontent.com/Bbambaaamm/rodinne-kino-kodi/main/dist/script.michal.family.repair/script.michal.family.repair-1.7.0.zip). V Kodi dej **Doplňky → Instalovat ze souboru ZIP** a vyber stažený soubor. Pro ruční instalaci ZIP povol **Neznámé zdroje**.
2. Otevři **Programové doplňky → Rodinné kino – instalace a servis** a potvrď instalaci. Kodi může vyžádat potvrzení instalace jednotlivých součástí a přepnutí na Arctic Fuse 3. Instalační postup uloží místní zálohu nastavení a své změny zaznamená pro obnovu. Pro aktuální závislosti vzhledu povolí aktualizace z libovolného repozitáře. Automatické dotazy Traktu na hodnocení vypne stejně jako v domácí sestavě.
3. Přihlas své účty v **Moje → Servis → Otevřít přihlášení Webshare** a **Otevřít přihlášení Trakt**. Trakt připoj také v nastavení **Doplňky → Programové doplňky → Trakt**, aby se zaznamenávalo přehrávání. U nového TMDb Helperu instalátor doplní samostatnou integraci Trakt.
4. V **Moje → Servis → Kontrola rodinného kina** ověř sestavu. ČSFD lze zapnout pod **Hodnocení ČSFD – Atlas** s vlastním klíčem a tarifem podporujícím ČSFD.

Na sestavě s vlastními úpravami Arctic Fuse 3 nejdřív uvolni vlastní nabídku na pozici 4, kterou použijí Streamovací služby. Při přerušeném stahování nebo odmítnutí systémového potvrzení lze instalátor znovu spustit. Již připravené součásti zkontroluje a pokračuje. Obnovu původního nastavení najdeš ve stejném servisním menu.

Instalátor rozšiřuje instalaci vzhledu z původního balíčku `michal-kodi-one-click-setup-1.0.2.zip` o aktuální Rodinné kino. Přibalený filmový doplněk má verzi **0.9.13**. Součásti třetích stran získává z [repozitáře autora Arctic Fuse](https://github.com/jurialmunkey/repository.jurialmunkey), [oficiálního repozitáře Kodi](https://kodi.tv/addons/omega/) a [zdroje Webshare – YAWSP](https://github.com/Webshare/Web). U přímo stahovaných ZIPů kontroluje otisk SHA-256. Instalační ZIP v sobě obsahuje náš aktuální filmový doplněk a úpravy, další součásti stáhne při instalaci.

Pro aktualizace z Kodi můžeš místo ručního stažení instalátoru nainstalovat [ZIP repozitáře Rodinné kino](https://raw.githubusercontent.com/Bbambaaamm/rodinne-kino-kodi/main/dist/repository.rodinne.kino/repository.rodinne.kino-1.0.0.zip) a pokračovat přes **Instalovat z repozitáře → Rodinné kino → Programové doplňky**. Po aktualizaci instalátoru spusť znovu **Nainstalovat Rodinné kino včetně vzhledu**, aby se aktualizoval také přibalený filmový doplněk.

## Účty a dostupnost

- Katalogy služeb ukazují nabídku pro ČR z dat TMDb a JustWatch. Pro přehrávání z Webshare se používá vlastní účet a soubory, ke kterým máš přístup. Karty služeb slouží k procházení katalogů.
- Přihlašovací údaje, klíče, historie a zálohy jsou uložené v instalaci uživatele. Zálohu lze obnovit v servisním menu, dokud je aktivní Arctic Fuse 3.
- Nastavení reprosoustavy, zvukového výstupu a projektoru patří ke konkrétnímu zařízení a nastavuje se v Kodi samostatně.
- Přihlašování probíhá přímo v Kodi. Osobní nabídky se naplní po připojení vlastního Traktu a přehrávání Webshare po vlastním přihlášení.

## Sestavení ze zdrojů

Spusť `python build.py`. Skript sestaví instalační ZIP, ZIP repozitáře a index pro Kodi v `dist/`. U obou ZIPů je kontrolní součet SHA-256. Filmový doplněk je ve `addons/plugin.video.webshare.available` a instalátor v `addons/script.michal.family.repair`.

## Ověření verze 1.7.0

Prošlo 162 stávajících kontrol filmového doplňku a 14 kontrol nového instalátoru, včetně čistého profilu, opakování po chybě a zachování existujících součástí. Úpravy vzhledu byly ověřeny proti původním souborům Arctic Fuse 3 verze 3.5.4. Obsah ZIPu, kontrolní součty a veřejné stažení jsou kontrolované při zveřejnění.

Kompletní průchod včetně systémových potvrzení na dalším fyzickém zařízení zůstává k ověření. Zkouška v odděleném Kodi 21.3 potvrdila registraci repozitáře a dostupnost vzhledu, při běhu se skrytým oknem se nepodařilo dokončit jeho instalační potvrzení. Obraz na projektoru a přehrávání ověřené na domácí sestavě se vztahují k jejímu zařízení a připojeným účtům.

Původní kód Rodinného kina je pod licencí MIT. Arctic Fuse 3 je dílo [jurialmunkey](https://github.com/jurialmunkey/skin.arctic.fuse.3) pod licencí [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Instalátor přidává úpravy do místně nainstalovaného vzhledu a jeho vlastní soubory zůstávají pod původní licencí. Webshare, Trakt a další služby spravují jejich provozovatelé.
