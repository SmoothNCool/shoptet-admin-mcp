"""MCP server shoptet-admin: správa Shoptet e-shopu přes jeho administraci (bez Premium API).

Spuštění: uv run --with mcp --with requests --with beautifulsoup4 --with paramiko python server.py
Konfigurace: proměnné prostředí nebo soubor v SHOPTET_ENV_FILE (formát KEY=value), viz README.md a .env.example.
"""
import os, re, pathlib
import requests
from bs4 import BeautifulSoup
from mcp.server.mcpserver import MCPServer

ENV_FILE = pathlib.Path(os.environ["SHOPTET_ENV_FILE"]) if os.environ.get("SHOPTET_ENV_FILE") else None
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def setting(key, default=None):
    if os.environ.get(key):
        return os.environ[key]
    if ENV_FILE and ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    if default is not None:
        return default
    raise RuntimeError(f"chybí {key} (nastav proměnnou prostředí nebo řádek v SHOPTET_ENV_FILE)")


SHOP = setting("SHOPTET_ADMIN_URL").rstrip("/")


def csrf(html):
    # token vkládá do formulářů až JS; server ho má v inline skriptu stránky (modální detaily ho nemají, pak bereme z /admin/)
    m = re.search(r'csrf\.token = "([^"]+)"', html)
    return m.group(1) if m else None


class Admin:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA

    def login(self):
        token = csrf(self.s.get(f"{SHOP}/admin/login/").text)
        r = self.s.post(f"{SHOP}/admin/login/", data={"action": "login", "email": setting("SHOPTET_ADMIN_USER"),
                                                      "password": setting("SHOPTET_ADMIN_PASS"), "__csrf__": token})
        if "/admin/login/" in r.url or 'name="password"' in r.text:
            raise RuntimeError(f"přihlášení do {SHOP} selhalo (status {r.status_code})")

    def get(self, path):
        r = self.s.get(SHOP + path)
        if "/admin/login/" in r.url:
            self.login()
            r = self.s.get(SHOP + path)
        return r.text

    def post_form(self, path, fields, files):
        body = [(k, (None, v.encode("utf-8"))) for k, v in fields]
        body += [(k, ("", b"", "application/octet-stream")) for k in files]
        return self.s.post(SHOP + path, files=body, headers={"Referer": SHOP + path, "Origin": SHOP})


admin = Admin()


def parse_form(html):
    """Formulář #main-form: serializace podle pravidel FormData + registr polí (typ, možnosti)."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="main-form")
    if form is None:
        raise RuntimeError("stránka neobsahuje formulář #main-form (neexistující ID produktu?)")
    fields, files, registry = [], [], {}

    def reg(name, kind, value=None, label=None):
        r = registry.setdefault(name, {"type": kind, "options": {}})
        if value is not None:
            r["options"][value] = label if label else value

    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or el.has_attr("disabled"):
            continue
        if el.name == "input":
            t = (el.get("type") or "text").lower()
            if t in ("submit", "button", "image", "reset"):
                continue
            if t == "file":
                files.append(name)
            elif t in ("checkbox", "radio"):
                lab = form.find("label", attrs={"for": el.get("id")}) if el.get("id") else None
                reg(name, t, el.get("value", "on"), lab.get_text(" ", strip=True) if lab else None)
                if el.has_attr("checked"):
                    fields.append((name, el.get("value", "on")))
            else:
                reg(name, t)
                fields.append((name, el.get("value", "")))
        elif el.name == "textarea":
            reg(name, "textarea")
            fields.append((name, el.get_text()))
        elif el.name == "select":
            opts = el.find_all("option")
            for o in opts:
                reg(name, "select", o.get("value", o.get_text()), o.get_text(strip=True))
            sel = [o for o in opts if o.has_attr("selected")]
            if not sel and not el.has_attr("multiple"):
                sel = [o for o in opts if not o.has_attr("disabled")][:1]
            for o in sel:
                fields.append((name, o.get("value", o.get_text())))
    if "__csrf__" not in dict(fields):
        fields.append(("__csrf__", csrf(html) or csrf(admin.get("/admin/"))))
    return form.get("action") or "", fields, files, registry


def values_by_name(fields):
    d = {}
    for k, v in fields:
        d.setdefault(k, []).append(v)
    d.pop("__csrf__", None)
    return {k: v[0] if len(v) == 1 and not k.endswith("[]") else v for k, v in d.items()}


server = MCPServer("shoptet-admin", instructions=f"Správa Shoptet e-shopu {SHOP} přes jeho administraci (bez API). "
                   "Produkty: product_find -> product_get -> product_update; hromadně products_bulk_update nejdřív bez apply. "
                   "Každá změna mění živý e-shop: provádět jen po výslovném potvrzení uživatelem a kontrolovat vrácený diff.")


FILTERS = {"brand": "manufacturerId", "category": "defaultCategoryId", "availability_sold_out": "availabilityId",
           "availability_in_stock": "availabilityInStockId", "visibility": "visibilityId", "stock_state": "stockState",
           "supplier": "supplierId", "item_type": "itemTypeId"}


def filter_form_options():
    soup = BeautifulSoup(admin.get("/admin/produkty/"), "html.parser")
    out = {}
    for name, key in FILTERS.items():
        sel = soup.select_one(f"#filter-form select[name={key}]")
        out[name] = {o.get("value", ""): o.get_text(strip=True) for o in sel.find_all("option") if o.get("value")}
    return out


def resolve(options, label):
    """Hodnota filtru: přímo ID, nebo popisek (bez ohledu na velikost písmen)."""
    if label in options:
        return label
    hits = [v for v, t in options.items() if t.lower() == label.lower()]
    if len(hits) != 1:
        raise ValueError(f"'{label}' neodpovídá právě jedné volbě: {options}")
    return hits[0]


@server.tool()
def filter_options() -> dict:
    """Povolené hodnoty filtrů pro product_find (značky, kategorie, dostupnosti, viditelnost, stav skladu...) jako {id: popisek}."""
    return filter_form_options()


@server.tool()
def product_find(code: str = "", name: str = "", brand: str = "", category: str = "", availability_sold_out: str = "",
                 availability_in_stock: str = "", visibility: str = "", stock_state: str = "", supplier: str = "",
                 item_type: str = "", max_pages: int = 4) -> dict:
    """Najde produkty v přehledu adminu. code = přesně/prefix, name = část názvu; ostatní filtry berou popisek nebo ID
    (viz filter_options). Stránka má 250 položek, max_pages omezuje počet načtených stránek. Vrací total a items (id, název, značka, viditelnost, cena)."""
    q = {"f[code]": code, "f[productName]": name}
    labels = {k: v for k, v in locals().items() if k in FILTERS and v}
    if labels:
        opts = filter_form_options()
        for k, v in labels.items():
            q[f"f[{FILTERS[k]}]"] = resolve(opts[k], v)
    base = "/admin/produkty/?" + "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in q.items() if v)
    items, total, page = [], None, 1
    while page <= max_pages:
        soup = BeautifulSoup(admin.get(f"{base}&from={page}"), "html.parser")
        if total is None:
            m = re.search(r"(\d[\d\s]*)\s*polo\S+ celkem", soup.get_text(" "))
            total = int(m.group(1).replace(" ", "")) if m else None
        rows = soup.select("a.table__detailLink[href*='produkty-detail/?id=']")
        for a in rows:
            tr = a.find_parent("tr")
            vis = tr.select_one(".product-visibility")
            price = tr.select_one(".table__cell--pricePrimary")
            brand_el = a.select_one(".grey")
            items.append({"id": int(re.search(r"id=(\d+)", a["href"]).group(1)),
                          "name": (a.find("strong") or a).get_text(strip=True),
                          "brand": brand_el.get_text(strip=True).split(":", 1)[-1].strip() if brand_el else "",
                          "visibility": vis.get("title", "") if vis else "",
                          "price": price.get_text(strip=True) if price else ""})
        if len(rows) < 250 or (total and len(items) >= total):
            break
        page += 1
    return {"total": total if total is not None else len(items), "loaded": len(items), "items": items}


def safe_path(path):
    """Jen cesty v adminu bez parametru action (mazání/přepínání jde v adminu přes GET s action=...)."""
    from urllib.parse import urlsplit, parse_qsl, unquote
    u = urlsplit(path)
    keys = {unquote(k).strip().lower() for k, _ in parse_qsl(u.query, keep_blank_values=True)}
    if u.scheme or u.netloc or not u.path.startswith("/admin/") or ".." in u.path or "action" in keys:
        raise ValueError("cesta musí začínat /admin/ a nesmí obsahovat parametr action (odkazy na mazání/přepínání)")
    return path


def safe_local(path):
    """Soubor k nahrání: nikdy nic ze složky se SHOPTET_ENV_FILE, z ~/.ssh ani .env soubory."""
    src = pathlib.Path(path).resolve()
    forbidden_dirs = [(pathlib.Path.home() / ".ssh").resolve()] + ([ENV_FILE.parent.resolve()] if ENV_FILE else [])
    for forbidden in forbidden_dirs:
        if src == forbidden or forbidden in src.parents:
            raise ValueError(f"soubor z {forbidden} se nahrávat nesmí")
    if src.name.startswith(".env") or not src.is_file():
        raise ValueError("nahrát lze jen existující běžný soubor, ne .env")
    return src


def safe_name(name):
    if "/" in name or chr(92) in name or name in (".", "..") or name.startswith("."):
        raise ValueError(f"neplatný název souboru: {name!r}")
    return name


def form_get(path, with_options=True):
    _, fields, _, registry = parse_form(admin.get(safe_path(path)))
    result = {"path": path, "fields": values_by_name(fields)}
    if with_options:
        opts = {}
        for name, r in registry.items():
            if r["options"]:
                opts.setdefault(re.sub(r"\[\d+\]", "[]", name), r["options"])
        result["options"] = opts
    return result


def form_update(path, changes):
    safe_path(path)
    action, fields, files, registry = parse_form(admin.get(path))
    before = values_by_name(fields)
    unknown = [k for k in changes if k not in registry]
    if unknown:
        return {"error": f"pole nejsou ve formuláři: {unknown}", "diff": {}}
    bad = {}
    for k, v in changes.items():
        vals = v if isinstance(v, list) else [v]
        allowed = registry[k]["options"]
        if allowed and any(x not in allowed for x in vals):
            bad[k] = {"zadano": vals, "povoleno": allowed}
        if len(vals) > 1 and not k.endswith("[]"):
            bad[k] = "pole nese jen jednu hodnotu"
    if bad:
        return {"error": "neplatné hodnoty", "detail": bad, "diff": {}}
    fields = [(k, v) for k, v in fields if k not in changes]
    for k, v in changes.items():
        fields += [(k, x) for x in (v if isinstance(v, list) else [v])]
    r = admin.post_form(action.replace(SHOP, "") if action else path, fields, files)
    errors = [e.get_text(" ", strip=True) for e in BeautifulSoup(r.text, "html.parser").select(".alert-danger, .error, .msg-error")]
    _, fields2, _, _ = parse_form(admin.get(path))
    after = values_by_name(fields2)
    diff = {k: {"before": before.get(k), "after": after.get(k)} for k in set(before) | set(after) if before.get(k) != after.get(k)}
    unapplied = [k for k, v in changes.items() if after.get(k) != v]
    return {"status": r.status_code, "diff": diff, "errors": errors[:5], "unapplied": unapplied}


@server.tool()
def product_get(product_id: int, with_options: bool = True) -> dict:
    """Vrátí všechna pole produktového formuláře (varianty, dostupnosti, kategorie pageId[], parametry...).
    `options` = povolené hodnoty pro výběrová/zaškrtávací pole; klíč je jméno pole s [N] nahrazeným [] (sdílené pro varianty)."""
    return {"id": product_id, **form_get(f"/admin/produkty-detail/?id={product_id}", with_options)}


@server.tool()
def product_update(product_id: int, changes: dict[str, str | list[str]]) -> dict:
    """Změní zadaná pole produktu (jméno pole -> hodnota; u polí s více hodnotami, např. pageId[], je seznam kompletní nový výběr)
    a uloží celý formulář. Vrací diff před/po uložení, který musí odpovídat požadovaným změnám."""
    return form_update(f"/admin/produkty-detail/?id={product_id}", changes)


@server.tool()
def admin_sections() -> dict:
    """Mapa administrace: cesta -> název sekce (stránky, články, kategorie, značky, kupony, objednávky, vzhled...).
    Seznamy čti přes admin_list, detaily přes admin_form_get / admin_form_update."""
    soup = BeautifulSoup(admin.get("/admin/"), "html.parser")
    out = {}
    for a in soup.select("a[href^='/admin/']"):
        href = a["href"].split("?")[0]
        text = a.get_text(" ", strip=True)
        if text and href not in out and "action=" not in a["href"]:
            out[href] = text
    return out


@server.tool()
def admin_list(path: str, page: int = 1) -> dict:
    """Přehledová stránka adminu (např. /admin/stranky/, /admin/kategorie/, /admin/znacky/, /admin/slevove-kupony/):
    vrátí řádky tabulky s odkazem na detail (id, detail_path, text řádku). Filtry lze předat v cestě jako f[pole]=hodnota, stránka = from."""
    safe_path(path)
    sep = "&" if "?" in path else "?"
    soup = BeautifulSoup(admin.get(f"{path}{sep}from={page}"), "html.parser")
    m = re.search(r"(\d[\d\s]*)\s*polo\S+ celkem", soup.get_text(" "))
    items, seen = [], set()
    for a in soup.select("a[href*='detail/?id='], a[href*='detail/?id='][class*=detailLink]"):
        href = a["href"]
        if not href.startswith("/admin/") or href in seen:
            continue
        seen.add(href)
        tr = a.find_parent("tr")
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")] if tr else [a.get_text(" ", strip=True)]
        items.append({"id": int(re.search(r"id=(\d+)", href).group(1)), "detail_path": href,
                      "text": " | ".join(c for c in cells if c)[:300]})
    return {"total": int(m.group(1).replace(" ", "")) if m else len(items), "page": page, "items": items}


@server.tool()
def admin_form_get(path: str, with_options: bool = True) -> dict:
    """Načte formulář #main-form na libovolné stránce adminu (detail stránky/článku/kategorie/značky/kuponu, Titulní strana,
    Editor vzhledu...). Vrací fields a options stejně jako product_get."""
    return form_get(path, with_options)


@server.tool()
def admin_form_update(path: str, changes: dict[str, str | list[str]]) -> dict:
    """Změní pole formuláře #main-form na dané stránce adminu a uloží ho; vrací diff před/po. Funguje všude, kde admin_form_get
    vrátí formulář. Mění živý e-shop, používat jen po potvrzení uživatelem a kontrolovat diff."""
    return form_update(path, changes)


def expand(product_fields, changes, only_if):
    """Rozepíše klíče s [*] na konkrétní indexy produktu; only_if (stejné klíče) omezí, kde se změna použije."""
    out = {}
    for key, val in changes.items():
        if "[*]" not in key:
            if all(product_fields.get(c) == v for c, v in only_if.items()):
                out[key] = val
            continue
        prefix = key.split("[*]")[0]
        for name in product_fields:
            m = re.match(re.escape(prefix) + r"\[(\d+)\]", name)
            if not m or name != key.replace("[*]", f"[{m.group(1)}]"):
                continue
            idx = m.group(1)
            if all(product_fields.get(c.replace("[*]", f"[{idx}]")) == v for c, v in only_if.items()):
                out[name] = val
    return out


@server.tool()
def products_bulk_update(product_ids: list[int], changes: dict[str, str | list[str]], only_if: dict[str, str] | None = None,
                         apply: bool = False) -> dict:
    """Hromadná změna přes více produktů. Klíče v changes mohou mít [*] = všechny varianty (např. variantAvailabilityId[*]);
    only_if = podmínka na aktuální hodnotu (např. {"variantAvailabilityId[*]": "-4"}). apply=False jen ukáže plán;
    apply=True uloží a vrátí pro každý produkt počet změněných polí, chyby a nepropsané změny."""
    only_if = only_if or {}
    report = []
    for pid in product_ids:
        f = product_get(pid, with_options=False)["fields"]
        plan = expand(f, changes, only_if)
        row = {"id": pid, "name": f.get("name"), "planned": len(plan), "fields": sorted(plan)}
        if plan and apply:
            r = product_update(pid, plan)
            row.update(status=r.get("status"), error=r.get("error"), errors=r.get("errors"), unapplied=r.get("unapplied"),
                       applied=len([k for k in plan if k in r.get("diff", {})]),
                       other_changed=sorted({re.sub(r"\[\d+\]", "[]", k) for k in r.get("diff", {}) if k not in plan}))
        report.append(row)
    return {"apply": apply, "products": len(report), "planned_total": sum(r["planned"] for r in report), "report": report}


FM = "/cms/libs/filemanager/"
FM_ROOT = "/user/documents/upload/"


def fm_dialog(folder):
    r = admin.s.get(SHOP + FM + "dialog.php", params={"type": "0", "lang": "cs_CZ", "popup": "0", "field_id": "", "akey": "key", "fldr": folder},
                    headers={"Referer": SHOP + "/admin/spravce-souboru/"})
    if "myAwesomeDropzone" not in r.text:
        admin.login()
        r = admin.s.get(r.url, headers={"Referer": SHOP + "/admin/spravce-souboru/"})
    return BeautifulSoup(r.text, "html.parser")


@server.tool()
def files_list(folder: str = "") -> dict:
    """Správce souborů (Vzhled a obsah -> Správce souborů): výpis složky, např. "" (kořen) nebo "obrazky/".
    Vrací podsložky a soubory s veřejnou URL (/user/documents/upload/...)."""
    folder = folder.strip("/") + "/" if folder.strip("/") else ""
    soup = fm_dialog(folder)
    folders, files = [], []
    for fig in soup.select("figure[data-name]"):
        name = fig["data-name"]
        if "back-directory" in (fig.get("class") or []):
            continue
        if "directory" in (fig.get("class") or []):
            folders.append(name)
        else:
            files.append({"name": name, "url": SHOP + FM_ROOT + requests.utils.quote(folder + name),
                          "info": " ".join(fig.get_text(" ", strip=True).split()[1:])[:80]})
    return {"folder": folder, "folders": folders, "files": files}


@server.tool()
def files_upload(local_path: str, folder: str = "") -> dict:
    """Nahraje lokální soubor (obrázek, PDF...) do správce souborů e-shopu do dané složky (musí existovat). Vrací veřejnou URL."""
    folder = folder.strip("/") + "/" if folder.strip("/") else ""
    dz = fm_dialog(folder).find("form", id="myAwesomeDropzone")
    data = {i["name"]: i.get("value", "") for i in dz.find_all("input") if i.get("name") and i.get("type") not in ("file", "submit")}
    data["fldr"] = folder
    src = safe_local(local_path)
    safe_name(src.name)
    with src.open("rb") as fh:
        r = admin.s.post(SHOP + FM + "upload.php", data=data, files={"file": (src.name, fh)},
                         headers={"Referer": SHOP + FM + "dialog.php"})
    ok = any(f["name"] == src.name for f in files_list(folder)["files"])
    return {"status": r.status_code, "uploaded": ok, "url": SHOP + FM_ROOT + requests.utils.quote(folder + src.name) if ok else None,
            "response": r.text[:200] if not ok else ""}


@server.tool()
def admin_form_create(path: str, changes: dict[str, str | list[str]]) -> dict:
    """Založí nový záznam přes prázdný formulář #main-form (např. /admin/stranka-detail/ bez id = nová stránka):
    vyplní zadaná pole a odešle. Vrací URL po uložení (obsahuje id nového záznamu) a případné chyby. Mění živý e-shop."""
    safe_path(path)
    action, fields, files, registry = parse_form(admin.get(path))
    unknown = [k for k in changes if k not in registry]
    if unknown:
        return {"error": f"pole nejsou ve formuláři: {unknown}"}
    fields = [(k, v) for k, v in fields if k not in changes]
    for k, v in changes.items():
        fields += [(k, x) for x in (v if isinstance(v, list) else [v])]
    r = admin.post_form(action.replace(SHOP, "") if action else path, fields, files)
    soup = BeautifulSoup(r.text, "html.parser")
    errors = [e.get_text(" ", strip=True) for e in soup.select(".alert-danger, .error, .msg-error")]
    m = re.search(r"[?&]id=(\d+)", r.url)
    return {"status": r.status_code, "url": r.url, "id": int(m.group(1)) if m else None, "errors": errors[:5]}


@server.tool()
def files_create_folder(name: str, parent: str = "") -> dict:
    """Založí novou složku ve správci souborů (v kořeni nebo v existující složce parent). Vrací, zda po založení existuje."""
    parent = parent.strip("/") + "/" if parent.strip("/") else ""
    soup = fm_dialog(parent)
    thumb = (soup.find(id="cur_dir_thumb") or {}).get("value", "")
    admin.s.post(SHOP + FM + "execute.php", params={"action": "create_folder"},
                 data={"path": parent + name, "path_thumb": thumb + name}, headers={"Referer": SHOP + FM + "dialog.php"})
    return {"folder": parent + name, "created": name in files_list(parent)["folders"]}


# SFTP (Shoptet: sftp://ftp.myshoptet.com, port 22; kořen = /user/documents/, složka upload = Správce souborů)
# otisk ed25519 klíče ftp.myshoptet.com (admin: Nastavení -> Hosting -> FTP); jiný klíč = nepřipojovat
SFTP_HOST_KEY_SHA256 = setting("SHOPTET_SFTP_HOST_KEY_SHA256", "bNX2DEUrb+uve8s22CVEa8Z1dzLAjUZKQXEpj5wLOxU")


def sftp_client():
    import paramiko, hashlib, base64
    host = setting("SHOPTET_SFTP_HOST", "ftp.myshoptet.com").replace("sftp://", "").replace("ftp://", "")
    t = paramiko.Transport((host, 22))
    t.start_client()
    got = base64.b64encode(hashlib.sha256(t.get_remote_server_key().asbytes()).digest()).decode().rstrip("=")
    if got != SFTP_HOST_KEY_SHA256:
        t.close()
        raise RuntimeError(f"SFTP klíč serveru nesedí ({got}), možný MITM – ověř otisk v adminu a nastav SHOPTET_SFTP_HOST_KEY_SHA256")
    t.auth_password(setting("SHOPTET_SFTP_USER"), setting("SHOPTET_SFTP_PASS"))
    return t, paramiko.SFTPClient.from_transport(t)


@server.tool()
def sftp_list(folder: str = "upload") -> dict:
    """Výpis složky přes SFTP e-shopu (kořen = /user/documents/; "upload" = Správce souborů). Vrací soubory s velikostí a veřejnou URL."""
    c, s = sftp_client()
    try:
        items = s.listdir_attr(folder)
    finally:
        c.close()
    import stat
    base = SHOP + "/user/documents/" + requests.utils.quote(folder.strip("/") + "/")
    return {"folder": folder, "folders": sorted(i.filename for i in items if stat.S_ISDIR(i.st_mode)),
            "files": sorted(({"name": i.filename, "size": i.st_size, "url": base + requests.utils.quote(i.filename)} for i in items if not stat.S_ISDIR(i.st_mode)), key=lambda x: x["name"])}


@server.tool()
def sftp_upload(local_path: str, remote_folder: str = "upload", remote_name: str = "") -> dict:
    """Nahraje lokální soubor přes SFTP do složky e-shopu (výchozí "upload" = Správce souborů; podsložky jako "upload/obrazky").
    Složka musí existovat. Vrací veřejnou URL a velikost ověřenou po nahrání."""
    src = safe_local(local_path)
    name = safe_name(remote_name or src.name)
    folder = remote_folder.strip("/")
    if ".." in folder.split("/"):
        raise ValueError("remote_folder nesmí obsahovat ..")
    remote = folder + "/" + name
    c, s = sftp_client()
    try:
        s.put(str(src), remote)
        size = s.stat(remote).st_size
    finally:
        c.close()
    return {"remote": remote, "size": size, "ok": size == src.stat().st_size,
            "url": SHOP + "/user/documents/" + requests.utils.quote(remote)}


# Export produktů (Produkty -> Export): admin vrátí soubor rovnou v odpovědi
EXPORT_DIR = pathlib.Path(setting("SHOPTET_EXPORT_DIR", str(pathlib.Path.home() / "Downloads" / "shoptet-export")))
EXPORT_FILTERS = {"brand": "manufacturerId", "category": "categoryId", "default_category": "defaultCategoryId",
                  "availability_sold_out": "availabilityId", "availability_in_stock": "availabilityInStockId",
                  "visibility": "visibilityId", "stock_state": "stockState", "item_type": "itemTypeId"}


def export_form():
    html = admin.get("/admin/export-produktu/")
    soup = BeautifulSoup(html, "html.parser")
    templates = {}
    for r in soup.select("#main-form input[name=type]"):
        par = r.find_parent(["label", "div", "li", "tr"])
        label = re.sub(r"\s+", " ", par.get_text(" ", strip=True)) if par else r["value"]
        label = re.sub(r"\s*,\s*vlastnosti\s*$", "", label)
        templates[r["value"]] = label
    return html, templates


@server.tool()
def export_templates() -> dict:
    """Šablony exportu produktů dostupné v adminu (hodnota -> popisek). Systémové mají záporné ID a jsou na všech webech,
    vlastní šablony se po webech liší. Výchozí pro products_export je kompletní XML (productsComplete;-5;xml)."""
    return export_form()[1]


@server.tool()
def products_export(template: str = "productsComplete;-5;xml", format: str = "", code: str = "", name: str = "", brand: str = "",
                    category: str = "", default_category: str = "", availability_sold_out: str = "", availability_in_stock: str = "",
                    visibility: str = "", stock_state: str = "", item_type: str = "", only_visible: bool = False,
                    out_path: str = "", preview_rows: int = 0) -> dict:
    """Stáhne export produktů z adminu do souboru a vrátí cestu + souhrn (nikdy celý obsah). template = hodnota z export_templates
    nebo část popisku (např. "Kompletní export - csv"); format csv/xls/xml (výchozí podle šablony). Filtry jako u product_find
    (popisek nebo ID). CSV je windows-1250 se středníkem; preview_rows vrátí prvních N řádků CSV jako slovníky."""
    html, templates = export_form()
    if template not in templates:
        # nejdřív přesný popisek bez předpony „systémové : / vlastní : “ a bez přípony formátů, pak podřetězec
        exact = [v for v, t in templates.items() if re.sub(r"^\w+ : |\s*-\s*(csv, xlsx|xml)$", "", t).lower() == template.lower()]
        hits = exact or [v for v, t in templates.items() if template.lower() in t.lower()]
        if len(hits) != 1:
            raise ValueError(f"šablona '{template}' neodpovídá právě jedné: {templates}")
        template = hits[0]
    fmt = format or ("xml" if template.endswith("xml") else "csv")
    action, fields, files, registry = parse_form(html)
    changes = {"type": template, "format": fmt, "code": code, "productName": name}
    if only_visible:
        changes["onlyVisible"] = "1"
    labels = {k: v for k, v in locals().items() if k in EXPORT_FILTERS and v}
    for k, v in labels.items():
        changes[EXPORT_FILTERS[k]] = resolve(registry[EXPORT_FILTERS[k]]["options"], v)
    fields = [(k, v) for k, v in fields if k not in changes] + list(changes.items())
    r = admin.post_form("/admin/export-produktu/", fields, files)
    cd = r.headers.get("content-disposition", "")
    if r.status_code != 200 or "attachment" not in cd:
        return {"error": f"admin nevrátil soubor (status {r.status_code}, content-type {r.headers.get('content-type')})"}
    ext = re.search(r'filename="[^"]*\.(\w+)"', cd).group(1)
    import datetime
    out = pathlib.Path(out_path) if out_path else EXPORT_DIR / f"{SHOP.replace('https://www.', '')}-{template.split(';')[1]}-{datetime.datetime.now():%Y%m%d-%H%M%S}.{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    info = {"path": str(out), "bytes": len(r.content), "format": ext}
    if ext == "xml":
        info["items"] = r.content.count(b"<SHOPITEM")
    else:
        import csv, io
        text = r.content.decode("windows-1250")
        rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
        info.update(encoding="windows-1250", delimiter=";", rows=len(rows), columns=list(rows[0].keys()) if rows else [])
        if preview_rows:
            info["preview"] = [{k: (v[:80] if isinstance(v, str) else v) for k, v in row.items() if v} for row in rows[:preview_rows]]
    return info


# Import produktů (Produkty -> Import): nový admin je Inertia aplikace, formulář jde XHR na stejnou URL
IMPORT_MODES = {"keep": 2, "included": 3, "replace_all": 1}


def inertia_page(path):
    import json
    soup = BeautifulSoup(admin.get(path), "html.parser")
    return json.loads(soup.find(id="app")["data-page"])


def inertia_get(path, version):
    r = admin.s.get(SHOP + path, headers={"X-Inertia": "true", "X-Inertia-Version": version,
                                          "X-Requested-With": "XMLHttpRequest", "Accept": "text/html, application/xhtml+xml"})
    return r.json()


@server.tool()
def products_import_log(limit: int = 20) -> dict:
    """Log importu produktů (Produkty -> Import -> Log): poslední záznamy s úrovní (1 info, 2 varování, 4 chyba) a stav zámku importu."""
    page = inertia_page("/admin/import-produktu/")
    data = inertia_get("/admin/import-produktu/log/", page["version"])["props"]["data"]
    logs = data["logs"]["logs"][:limit]
    return {"lock": page["props"]["data"].get("lock"), "total": data["logs"]["pagination"]["foundRows"],
            "logs": [{"id": x["id"], "date": x["date"]["date"][:19], "level": {1: "info", 2: "warning", 4: "error"}.get(x["logLevel"], x["logLevel"]),
                      "message": re.sub(r"<[^>]+>", "", x["title"])} for x in logs]}


@server.tool()
def products_import(local_path: str, mode: str = "keep", redirect_urls: bool = True, change_url_by_name: bool = False,
                    apply_empty_values: bool = False, wait_seconds: int = 60) -> dict:
    """Nahraje CSV/XLSX/XML do importu produktů a spustí ho. mode: keep = produkty mimo soubor nechat (výchozí, bezpečné),
    included = u produktů v souboru smazat varianty, které v něm chybí, replace_all = SMAZAT vše, co v souboru není (nebezpečné).
    Existující produkty se párují podle code + pairCode; nový produkt potřebuje code, pairCode, name, price. Prázdné hodnoty
    se bez apply_empty_values přeskakují. CSV windows-1250 nebo UTF-8 se středníkem. Vrací odpověď adminu a log po doběhnutí."""
    import time
    if mode not in IMPORT_MODES:
        raise ValueError(f"mode musí být jedno z {list(IMPORT_MODES)}")
    src = pathlib.Path(local_path)
    page = inertia_page("/admin/import-produktu/")
    if page["props"]["data"].get("lock"):
        return {"error": "import je zamčený (běží nebo nedoběhl předchozí)", "lock": page["props"]["data"]["lock"]}
    before = products_import_log(1)["logs"]
    last_id = before[0]["id"] if before else 0
    data = {"action": "import", "importType": str(IMPORT_MODES[mode]), "redirectUrls": "1" if redirect_urls else "0",
            "changeUrlByName": "1" if change_url_by_name else "0", "applyEmptyValues": "1" if apply_empty_values else "0",
            "__csrf__": page["props"]["appState"]["csrf"]}
    with src.open("rb") as fh:
        r = admin.s.post(SHOP + "/admin/import-produktu/", data=data, files={"file": (src.name, fh)},
                         headers={"X-Inertia": "true", "X-Inertia-Version": page["version"], "X-Requested-With": "XMLHttpRequest",
                                  "Accept": "text/html, application/xhtml+xml", "Referer": SHOP + "/admin/import-produktu/"})
    result = {"status": r.status_code, "file": src.name, "mode": mode}
    try:
        j = r.json()
        result["component"] = j.get("component"); result["notifier"] = j.get("props", {}).get("meta", {}).get("notifier")
        result["errors"] = j.get("props", {}).get("errors")
    except ValueError:
        result["response"] = r.text[:300]
    # počkat na doběhnutí (zámek zmizí) a vrátit nové řádky logu
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(3)
        if not inertia_page("/admin/import-produktu/")["props"]["data"].get("lock"):
            break
    log = products_import_log(50)
    result["finished"] = not log["lock"]
    result["log"] = [x for x in log["logs"] if x["id"] > last_id]
    return result


if __name__ == "__main__":
    if setting("SHOPTET_MCP_TRANSPORT", "stdio") == "http":
        # vzdálený režim (ChatGPT, web klienti): HTTPS zajisti tunelem nebo reverzní proxy, tajná cesta nahrazuje autentizaci
        from mcp.server.transport_security import TransportSecuritySettings
        hosts = [h.strip() for h in setting("SHOPTET_MCP_ALLOWED_HOSTS", "-").split(",") if h.strip() and h.strip() != "-"]
        server.run("streamable-http", host=setting("SHOPTET_MCP_HOST", "127.0.0.1"), port=int(setting("SHOPTET_MCP_PORT", "8765")),
                   streamable_http_path=setting("SHOPTET_MCP_PATH", "/mcp"),
                   transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=bool(hosts), allowed_hosts=hosts))
    else:
        server.run()
