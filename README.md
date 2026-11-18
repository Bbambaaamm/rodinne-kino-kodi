# Rodinné kino pro Kodi

České filmové prostředí pro Kodi s nabídkami Domů, Filmy, Seriály, Moje a Streamovací služby. Hledá podle názvu, herce a roku, umí procházet žánry, postupně doplňuje seznamy a otevírá filmy, řady a díly ve stejném okně. Na plakátech ukazuje zhlédnutí a průběh přehrávání z Traktu. Při výběru zdrojů dává přednost českému zvuku a 1080p. Hodnocení ČSFD z Atlasu je volitelné.

## Instalace

Plné rozhraní je určené pro **Kodi 21 Omega s aktivním vzhledem Arctic Fuse 3**. Domácí sestava, ze které vydání vychází, běží na Android TV. Ověření vydání na jednotlivých platformách se může lišit.

1. Přidej [repozitář autora Arctic Fuse](https://github.com/jurialmunkey/repository.jurialmunkey), nainstaluj **Arctic Fuse 3 pro Kodi Omega** a aktivuj ho. Kodi doinstaluje potřebné komponenty vzhledu, včetně Skin Variables a TMDb Helperu podle verze vzhledu.
2. Nainstaluj a zapni [Trakt pro Kodi](https://kodi.tv/addons/omega/script.trakt/) a [Webshare – YAWSP](https://github.com/Webshare/Web/blob/main/plugin.video.yawsp-master.zip). Přihlas se vlastním účtem ve Webshare a Traktu. Trakt připoj také v nastavení **TMDb Helper → Trakt** kvůli osobním seznamům, historii a doporučením.
3. Stáhni [instalační ZIP Rodinného kina](https://raw.githubusercontent.com/Bbambaaamm/rodinne-kino-kodi/main/dist/script.michal.family.repair/script.michal.family.repair-1.6.19.zip). V Kodi dej **Doplňky → Instalovat ze souboru ZIP** a vyber uložený soubor. Pro ruční instalaci ZIP Kodi vyžaduje povolit **Neznámé zdroje**. ZIP obsahuje instalátor i filmový doplněk.
4. Otevři **Programové doplňky → Rodinné kino – instalace a servis → Použít ověřené rodinné nastavení**. Potvrzením se uloží místní záloha a nastaví se nabídky Arctic Fuse 3, ovládání a přehrávač. Pokud už máš ve vzhledu vlastní nabídku na pozici 4, uvolni ji před spuštěním instalátoru.
5. Po návratu do Kodi ověř **Moje → Servis → Kontrola rodinného kina**. ČSFD lze zapnout ve stejném menu pod **Hodnocení ČSFD – Atlas** s vlastním klíčem a tarifem podporujícím ČSFD.

Pro aktualizace z Kodi můžeš místo ručního stažení instalátoru nainstalovat [ZIP repozitáře Rodinné kino](https://raw.githubusercontent.com/Bbambaaamm/rodinne-kino-kodi/main/dist/repository.rodinne.kino/repository.rodinne.kino-1.0.0.zip) a pokračovat přes **Instalovat z repozitáře → Rodinné kino → Programové doplňky**. Po aktualizaci instalátoru spusť znovu **Použít ověřené rodinné nastavení**, aby se aktualizoval také přibalený filmový doplněk.

## Účty a dostupnost

- Katalogy služeb ukazují nabídku pro ČR z dat TMDb a JustWatch. Pro přehrávání z Webshare se používá vlastní účet a soubory, ke kterým máš přístup. Karty služeb slouží k procházení katalogů.
- Přihlašovací údaje, klíče, historie a zálohy jsou uložené v instalaci uživatele. Zálohu lze obnovit v servisním menu, dokud je aktivní Arctic Fuse 3.
- Nastavení reprosoustavy, zvukového výstupu a projektoru patří ke konkrétnímu zařízení a nastavuje se v Kodi samostatně.

## Sestavení ze zdrojů

Spusť `python build.py`. Skript sestaví instalační ZIP, ZIP repozitáře a index pro Kodi v `dist/`. U obou ZIPů je kontrolní součet SHA-256. Filmový doplněk je ve `addons/plugin.video.webshare.available` a instalátor v `addons/script.michal.family.repair`.

Původní kód Rodinného kina je pod licencí MIT. Arctic Fuse 3 je dílo [jurialmunkey](https://github.com/jurialmunkey/skin.arctic.fuse.3) pod licencí [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Instalátor přidává úpravy do místně nainstalovaného vzhledu a jeho vlastní soubory zůstávají pod původní licencí. Webshare, Trakt a další služby spravují jejich provozovatelé.
