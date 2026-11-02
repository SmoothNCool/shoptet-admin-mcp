# shoptet-admin – MCP server pro úpravy produktů bez Shoptet Premium

Oficiální Shoptet MCP na Core tarifu neumí dostupnosti variant, zařazení produktu do více kategorií
ani další pole produktového formuláře. Tenhle server se přihlásí do administrace jako člověk
a pracuje přímo s formulářem detailu produktu (`/admin/produkty-detail/?id=…`).

## Nástroje
- `filter_options()` – povolené hodnoty filtrů přehledu (značky, kategorie, dostupnosti, viditelnost, stav skladu, dodavatel, typ) jako {id: popisek}.
- `product_find(code, name, brand, category, availability_sold_out, availability_in_stock, visibility, stock_state, supplier, item_type, max_pages)` – hledání v přehledu produktů; filtry berou popisek nebo ID, stránkuje po 250 (`from=N`). Vrací total, loaded, items (id, název, značka, viditelnost, cena).
- `product_get(id)` – všechna pole formuláře + povolené hodnoty výběrových polí (`options`, klíč `pole[]` sdílený pro varianty).
- `product_update(id, changes)` – změní pole a uloží celý formulář; vrací diff před/po, `errors` a `unapplied`.
  Pole s více hodnotami (`pageId[]` = kategorie) dostávají seznam = kompletní nový výběr.
- `products_bulk_update(product_ids, changes, only_if, apply)` – hromadná změna; klíč s `[*]` = všechny varianty
  (`variantAvailabilityId[*]`), `only_if` omezí na aktuální hodnotu (`{"variantAvailabilityId[*]": "-4"}`).
  `apply=False` vrátí jen plán (počet polí na produkt), `apply=True` uloží a vrátí applied / unapplied / errors / other_changed.

### Export katalogu
- `export_templates()` – šablony exportu v adminu (systémové se záporným ID jsou všude, vlastní se po webech liší).
- `products_export(template, format, filtry…, out_path, preview_rows)` – stáhne export do souboru (výchozí složka `~/Downloads/shoptet-export/`, přepíše `SHOPTET_EXPORT_DIR`) a vrátí cestu, velikost, počet položek a u CSV sloupce; obsah se do konverzace nevrací. Kompletní XML (`productsComplete;-5;xml`) má vše vč. variant; CSV je windows-1250 se středníkem.

### Import katalogu
- `products_import(local_path, mode, redirect_urls, change_url_by_name, apply_empty_values)` – nahraje CSV/XLSX/XML do Produkty → Import (nový admin = Inertia, POST na stejnou URL s `X-Inertia` a `__csrf__` z `appState`), počká na doběhnutí a vrátí nové řádky logu. `mode`: `keep` (výchozí, produkty mimo soubor nechat), `included` (u produktů v souboru smazat chybějící varianty), `replace_all` (smaže vše mimo soubor – jen s výslovným souhlasem). Párování code + pairCode; nový produkt = code, pairCode, name, price. Kategorie v `categoryText…` jsou kompletní seznam (přepisují!).
- `products_import_log(limit)` – log importu a stav zámku.

### Obecné nástroje nad celým adminem
- `admin_sections()` – mapa administrace (cesta → název sekce).
- `admin_list(path, page)` – řádky přehledové stránky s odkazem na detail (stránky, články, kategorie, značky, kupóny…); filtry jako `f[pole]=hodnota` v cestě.
- `admin_form_get(path)` / `admin_form_update(path, changes)` – libovolný formulář `#main-form` (detail stránky/článku/kategorie/značky/kupónu, Titulní strana, Editor vzhledu). Cesty s `action=` (mazání, přepínání) jsou odmítnuté.
- `admin_form_create(path, changes)` – nový záznam přes prázdný formulář (např. `/admin/stranka-detail/` = nová stránka). Admin po uložení nepřesměruje na id, nový záznam dohledej v `admin_list`.
- `files_list(folder)` / `files_upload(local_path, folder)` – Správce souborů (Responsive FileManager v iframu `/cms/libs/filemanager/`): výpis složky s veřejnými URL a nahrání souboru do existující složky. Mazání záměrně není. `files_create_folder(name, parent)` založí složku (`execute.php?action=create_folder`).
- `sftp_list(folder)` / `sftp_upload(local_path, remote_folder)` – totéž přes SFTP (`sftp://ftp.myshoptet.com`, port 22, kořen `/user/documents/`, složka `upload` = Správce souborů). Přístupy `<PREFIX>_FTP_HOST/USER/PASS` v `littleshoes.env` (LSCZ, LSSK, FOOTICCZ, FOOTICDE, FOOTICPL, FOOTICCOM). Vhodné pro větší nebo hromadné soubory; FTP na portu 21 Shoptet neprovozuje.

Objednávky, Bannery, Ceny, Slovník pojmů a Zákazníci se v adminu vykreslují JavaScriptem – obecné nástroje je nevidí.

## Jak to funguje
- Login: POST `/admin/login/` s `email`, `password`, `action=login` a `__csrf__`.
- CSRF token je v inline skriptu každé stránky (`csrf.token = "csrf_…"`); do formulářů ho vkládá až JS, bez něj admin vrací 403. Modální detaily (kupóny) token nemají, bere se z `/admin/`.
- Formulář se serializuje podle pravidel FormData (nezaškrtnuté checkboxy chybí, select bez `selected` = první volba, file inputy prázdné) a posílá multipart. Ověřeno: 176 polí shodně s prohlížečem, diff po uložení beze změny prázdný.

## Konfigurace
Jeden server = jeden e-shop (`SHOPTET_ADMIN_URL`). Přihlášení `ADMIN_USER` / `ADMIN_PASS` čte z `C:\Data\secrets\littleshoes.env`
(Davidův login platí pro všechny e-shopy). Registrace v Claude Code (scope user), např. pro footic.cz:

```
claude mcp add shoptet-admin-footic-cz -s user -e SHOPTET_ADMIN_URL=https://www.footic.cz -- <uv.exe> run --system-certs --with mcp --with requests --with beautifulsoup4 python <cesta>\server.py
```

## Kontrola
`uv run --system-certs --with mcp --with requests --with beautifulsoup4 --with paramiko python check.py` – živý test na footic.cz: skrytý produkt 92025 (find s filtry, get, zápis a návrat interní poznámky, bulk), admin_list/admin_form (uložení stránky a kategorie beze změny = prázdný diff, zápis a návrat poznámky kupónu), validace.

## Bezpečnostní pojistky
- Cesty do adminu musí začínat `/admin/` a nesmí nést parametr `action` (po dekódování, bez ohledu na velikost písmen) – tudy jdou v adminu mazání a přepínání.
- Nahrávat (správce souborů i SFTP) lze jen existující běžný soubor mimo složku s přístupy (`C:\Data\secrets`), mimo `~/.ssh` a ne `.env*`; název bez lomítek a teček na začátku, `remote_folder` bez `..`.
- SFTP ověřuje otisk klíče serveru (`SHOPTET_SFTP_HOST_KEY_SHA256`, výchozí = ftp.myshoptet.com z adminu); při neshodě se nepřipojí.

## Omezení
- Nevytváří produkty, varianty ani parametry (v adminu je generuje JS). Obrázky, objednávky a kategorie samotné řeší oficiální MCP.
- Ukládá celý formulář: u polí, která admin plní jen skriptem, by se hodnota mohla ztratit – proto se po každém uložení vrací diff.
- Hledání vrací jen první stránku přehledu (250 položek).
- Admin při každém uložení (i ručním) normalizuje prázdné `packageDimensions[…]` variant na `0`; u produktů z importu se to v diffu objeví jako vedlejší změna.

## Hromadné akce
Postup z konverzace: `product_find(brand=..., ...)` → `products_bulk_update(ids, changes, only_if)` jako náhled → po potvrzení totéž s `apply=True`.
ID hodnot dostupnosti se liší po e-shopech („2-3 dny“: CZ 14, PL 32, SK 41, COM 59; „1 týden“ všude -4) – vzít z `product_get` → `options`.
Příklad 2026-10-30: zimní Fooz na PL/SK/COM, 180 variant `variantAvailabilityId` -4 → 2-3 dny.
