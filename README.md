# shoptet-admin – MCP server pro správu Shoptet e-shopu bez Premium API

> **EN:** MCP server that manages a [Shoptet](https://www.shoptet.cz) e-shop through its administration UI, so it works on every plan without the Premium API. Tools cover products and variants (availability, stock, categories), bulk updates, any admin form (pages, articles, categories, brands, coupons), the file manager, SFTP, catalogue export and CSV import. Works with Claude Code, Claude Desktop and, in remote HTTP mode, ChatGPT or any MCP client. Documentation and tool descriptions are in Czech, the language of the platform. Use at your own risk: every write changes a live shop. MIT licence.

MCP server, který ovládá Shoptet e-shop přes jeho **administraci**, stejně jako by v ní klikal člověk. Funguje na všech tarifech, nepotřebuje Premium ani API doplněk. Umí to, co oficiální Shoptet MCP neumí: dostupnosti variant, zařazení produktu do více kategorií, hromadné změny přes filtr, libovolný formulář adminu (stránky, články, kategorie, značky, kupóny), správce souborů, SFTP, export katalogu a CSV import.

Funguje s Claude Code, Claude Desktop a (ve vzdáleném režimu) s ChatGPT nebo jiným klientem, který umí MCP přes HTTP.

## Než začneš, přečti si

- **Mění živý e-shop.** Každé uložení je stejné jako kliknutí na Uložit v adminu. Nástroje vrací diff před/po, aby šlo každou změnu zkontrolovat, ale neexistuje tlačítko Zpět. Používej samostatný administrátorský účet pro robota a před hromadnou změnou si udělej export.
- **Shoptet drží jeden aktivní session na uživatele.** Když se server přihlásí účtem, který máš otevřený v prohlížeči, prohlížeč tě odhlásí. Další důvod pro samostatný účet.
- **Není to oficiální API.** Server čte a odesílá formuláře administrace. Když Shoptet admin změní, některý nástroj může přestat fungovat, dokud se neupraví. Je to tvoje odpovědnost i riziko.
- Server nic **nemaže** (záměrně) a odmítá adresy s parametrem `action` (tudy jdou v adminu mazání a přepínání).

## Instalace

Potřebuješ Python 3.11+ a [uv](https://docs.astral.sh/uv/). Nic dalšího se neinstaluje ručně, závislosti si `uv` stáhne při spuštění:

```
uv run --with mcp --with requests --with beautifulsoup4 --with paramiko python server.py
```

Na Windows s antivirem, který podepisuje TLS vlastní certifikátem (Norton apod.), přidej `--system-certs` za `uv run`.

## Konfigurace

Zkopíruj `.env.example` do vlastního souboru **mimo repozitář** (třeba `C:\secrets\shoptet-mujeshop.env`), vyplň ho a cestu předej v proměnné `SHOPTET_ENV_FILE`. Stejné klíče jdou nastavit i přímo jako proměnné prostředí, ty mají přednost. Jeden soubor = jeden e-shop.

**Víc e-shopů v jednom serveru:** místo `SHOPTET_ENV_FILE` nastav `SHOPTET_ENV_FILES="cz=C:\secrets\shop-cz.env;de=C:\secrets\shop-de.env"`. Každý nástroj pak má povinný parametr `eshop` (`cz`, `de`…), přihlášení drží server pro každý e-shop zvlášť. Společná nastavení (export, upload, HTTP režim) se berou z prvního souboru. Jeden proces místo několika šetří paměť.

| Proměnná | Povinná | Význam |
|---|---|---|
| `SHOPTET_ADMIN_URL` | ano | adresa e-shopu, např. `https://www.muj-eshop.cz` |
| `SHOPTET_ADMIN_USER`, `SHOPTET_ADMIN_PASS` | ano | přihlášení do administrace |
| `SHOPTET_SFTP_HOST`, `SHOPTET_SFTP_USER`, `SHOPTET_SFTP_PASS` | ne | SFTP účet z adminu (Nastavení → Hosting → FTP); bez něj nejsou nástroje `sftp_*` |
| `SHOPTET_SFTP_HOST_KEY_SHA256` | ne | otisk klíče SFTP serveru; výchozí platí pro `ftp.myshoptet.com`, při neshodě se server nepřipojí |
| `SHOPTET_EXPORT_DIR` | ne | složka pro exporty katalogu (výchozí `~/Downloads/shoptet-export`) |
| `SHOPTET_MCP_TRANSPORT` | ne | `stdio` (výchozí) nebo `http` pro vzdálený režim |
| `SHOPTET_MCP_HOST`, `SHOPTET_MCP_PORT`, `SHOPTET_MCP_PATH` | v HTTP režimu cesta ano | adresa, port a tajná cesta HTTP režimu (`/` + aspoň 32 náhodných znaků; bez ní server nenastartuje) |
| `SHOPTET_MCP_ALLOWED_HOSTS` | ne | hostname tunelu pro HTTP režim; localhost je povolený vždy, ostatní hlavičky Host server odmítá |
| `SHOPTET_MCP_TOKEN` | ne | Bearer token pro HTTP režim (klienti, které umí hlavičky) |
| `SHOPTET_UPLOAD_DIR` | v HTTP režimu ano | jediná složka, ze které smí server nahrávat a importovat soubory |

## Připojení ke klientům

### Claude Code

```
claude mcp add shoptet-mujeshop -s user -e SHOPTET_ENV_FILE=C:\secrets\shoptet-mujeshop.env -- uv run --with mcp --with requests --with beautifulsoup4 --with paramiko python C:\cesta\k\shoptet-admin\server.py
```

Víc e-shopů najednou: stejný příkaz s `-e SHOPTET_ENV_FILES="cz=C:\secrets\shop-cz.env;de=C:\secrets\shop-de.env"`.

### Claude Desktop

Do `claude_desktop_config.json` (Nastavení → Developer → Edit Config):

```json
{
  "mcpServers": {
    "shoptet-mujeshop": {
      "command": "uv",
      "args": ["run", "--with", "mcp", "--with", "requests", "--with", "beautifulsoup4", "--with", "paramiko", "python", "C:\\cesta\\k\\shoptet-admin\\server.py"],
      "env": { "SHOPTET_ENV_FILE": "C:\\secrets\\shoptet-mujeshop.env" }
    }
  }
}
```

### ChatGPT (a jiní klienti přes HTTP)

ChatGPT umí MCP jen jako **vzdálený server přes HTTPS** (zapíná se v Nastavení → Konektory → Developer mode; dostupné na tarifech Plus/Pro/Business/Enterprise). Postup:

1. Do konfigurace přidej `SHOPTET_MCP_TRANSPORT=http`, `SHOPTET_MCP_PATH=/` + aspoň 32 náhodných znaků (bez toho server odmítne nastartovat; ta cesta je jediná ochrana, protože ChatGPT neumí k vlastnímu serveru poslat token) a `SHOPTET_UPLOAD_DIR` se složkou, ze které smí server nahrávat a importovat (jiné soubory ve vzdáleném režimu odmítne). Spusť server stejným příkazem jako výše, poběží na `http://127.0.0.1:8765<cesta>`.
2. Vystav ho na HTTPS tunelem, např. `cloudflared tunnel --url http://127.0.0.1:8765` nebo `ngrok http 8765`. Hostname tunelu dej do `SHOPTET_MCP_ALLOWED_HOSTS`, jiné hlavičky Host server odmítá (ochrana proti DNS rebindingu je vždy zapnutá).
3. V ChatGPT vytvoř konektor: URL = adresa tunelu + tajná cesta, autentizace „žádná“. Klient, který umí hlavičky, může navíc posílat `Authorization: Bearer` s hodnotou `SHOPTET_MCP_TOKEN`.
4. Tunel i server vypni, když je nepoužíváš. Kdo zná URL, ovládá tvůj e-shop.

Stejnou adresu použije kterýkoli jiný klient s podporou MCP přes streamable HTTP.

## Nástroje

| Nástroj | Co dělá |
|---|---|
| `product_find(code, name, brand, category, availability_sold_out, availability_in_stock, visibility, stock_state, supplier, item_type, max_pages)` | hledání v přehledu produktů s filtry adminu (popisek nebo ID), stránkuje po 250 |
| `filter_options()` | povolené hodnoty filtrů (značky, kategorie, dostupnosti, viditelnost…) |
| `product_get(product_id)` | všechna pole produktového formuláře (varianty, dostupnosti, kategorie `pageId[]`, parametry…) a povolené hodnoty výběrových polí |
| `product_update(product_id, changes)` | změní zadaná pole a uloží celý formulář; vrací diff před/po, `errors`, `unapplied` |
| `products_bulk_update(product_ids, changes, only_if, apply)` | hromadná změna; `[*]` v klíči = všechny varianty, `only_if` = podmínka na aktuální hodnotu, bez `apply` jen plán |
| `admin_sections()` | mapa administrace (cesta → název) |
| `admin_list(path, page)` | řádky přehledové stránky s odkazy na detail (stránky, články, kategorie, značky, kupóny…) |
| `admin_form_get(path)`, `admin_form_update(path, changes)`, `admin_form_create(path, changes)` | libovolný formulář `#main-form` v adminu: čtení, uložení s diffem, založení nového záznamu |
| `files_list(folder)`, `files_upload(local_path, folder)`, `files_create_folder(name, parent)` | Správce souborů (veřejné URL `/user/documents/upload/…`) |
| `sftp_list(folder)`, `sftp_upload(local_path, remote_folder, remote_name)` | totéž přes SFTP (port 22, kořen `/user/documents/`) |
| `export_templates()`, `products_export(template, format, filtry…, out_path, preview_rows)` | export katalogu do souboru (kompletní XML nebo CSV windows-1250 se středníkem); obsah se do chatu nevrací |
| `products_import(local_path, mode, redirect_urls, change_url_by_name, apply_empty_values)`, `products_import_log(limit)` | CSV/XLSX/XML import přes Produkty → Import; `mode`: `keep` (výchozí), `included`, `replace_all` |

### Jak se pracuje s produktem

Pole mají jména z admin formuláře. Nejdůležitější:

- `variantAvailabilityId[<id varianty>]` dostupnost při vyprodání, `variantAvailabilityInStockId[...]` dostupnost skladem, `variantStock[...]` množství. Povolené hodnoty vrací `product_get` v `options` (ID se liší e-shop od e-shopu, systémové `-1` skladem, `-2` vyprodáno, `-4` 1 týden, `-5` na dotaz jsou všude).
- `pageId[]` kategorie produktu: seznam je **kompletní nový výběr**, chybějící kategorie se odeberou. Vždy nejdřív načti a doplň.
- `description`, `shortDescription`, `name`, `metaTitle`, `metaDescription`, `internalNote`, `visibility`, `defaultCategoryId`, `manufacturerId`.
- Admin při každém uložení normalizuje prázdné rozměry balení `packageDimensions[…]` na `0`. V diffu to není chyba.

### Hromadná změna

1. `product_find(brand="Značka", visibility="Viditelný")` nebo `products_export` pro celý katalog.
2. `products_bulk_update(ids, {"variantAvailabilityId[*]": "14"}, {"variantAvailabilityId[*]": "-4"})` → plán, kolik produktů a variant se změní.
3. Totéž s `apply=True`. V hlášení musí být `unapplied` a `errors` prázdné.

### CSV import

Párování existujících produktů podle `code` + `pairCode` (hodnoty vezmi z exportu). Nový produkt potřebuje `code`, `pairCode`, `name`, `price`; varianty stejný `pairCode` pod sebou. Posílej jen sloupce, které měníš; `categoryText…` je kompletní seznam kategorií. Prázdné hodnoty se přeskakují, mazání hodnot jen s `apply_empty_values=True`. `replace_all` smaže vše, co v souboru není. Nejdřív 1–3 řádky na zkoušku.

## Jak to funguje uvnitř

- Login: POST `/admin/login/` s e-mailem, heslem a `__csrf__`. CSRF token je v inline skriptu každé stránky (`csrf.token = "csrf_…"`); do formulářů ho vkládá až JavaScript, bez něj admin vrací 403.
- Formulář `#main-form` se serializuje podle pravidel `FormData` (nezaškrtnuté checkboxy chybí, select bez `selected` = první volba, file inputy prázdné) a posílá multipart na stejnou URL. Po uložení se stránka načte znovu a spočítá diff.
- Nový import (Produkty → Import) je Inertia aplikace: data stránky v atributu `data-page`, odeslání XHR s hlavičkou `X-Inertia` a tokenem z `appState.csrf`, log přes `/admin/import-produktu/log/`.
- Správce souborů je Responsive FileManager v iframu `/cms/libs/filemanager/` (upload `upload.php`, složka `execute.php?action=create_folder`).
- Objednávky, bannery, ceny, slovník pojmů a zákazníci se v adminu kreslí JavaScriptem; obecné nástroje je nevidí.

## Bezpečnostní pojistky

- Cesty do adminu musí začínat `/admin/` a nesmí nést parametr `action` (po dekódování, bez ohledu na velikost písmen).
- Nahrávat lze jen existující běžný soubor mimo složku se `SHOPTET_ENV_FILE`, mimo `~/.ssh` a ne `.env*`; název bez lomítek a teček na začátku, cílová složka bez `..`.
- SFTP ověřuje otisk klíče serveru; při neshodě se nepřipojí.
- HTTP režim nenastartuje bez dlouhé tajné cesty, volitelně vyžaduje Bearer token, odmítá cizí hlavičky Host a nahrává jen z `SHOPTET_UPLOAD_DIR`. Nikdy ho nevystavuj bez tunelu s HTTPS.

## Kontrola po změně kódu

`check.py` je živý test na jednom (ideálně skrytém) produktu: hledání s filtry, čtení, zápis a návrat interní poznámky, plán hromadné změny, obecné formuláře (uložení stránky a kategorie beze změny musí dát prázdný diff, zápis a návrat poznámky u prvního kupónu), validace.

```
SHOPTET_ENV_FILE=... SHOPTET_TEST_PRODUCT_ID=123 SHOPTET_TEST_PRODUCT_CODE=ABC SHOPTET_TEST_PRODUCT_NAME="začátek názvu" SHOPTET_TEST_BRAND="Značka" uv run --with mcp --with requests --with beautifulsoup4 --with paramiko python check.py
```

## Licence a přispívání

MIT (viz `LICENSE`). Autor: David Zelenka. Chyby a nápady posílej jako issue; než pošleš pull request, pusť `check.py` proti vlastnímu testovacímu produktu. Projekt není nijak spojený se společností Shoptet.

## Omezení

- Nezakládá produkty ani varianty přes formulář (admin je staví JavaScriptem); na to je `products_import`.
- Nemaže nic (záměrně).
- Hledání vrací jen přehledové sloupce; detail dá `product_get`.
- Vlastní šablony exportu mají na každém e-shopu jiné ID; systémové (záporné) jsou všude stejné.
