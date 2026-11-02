"""Živá kontrola serveru na testovacím produktu (ideálně skrytém) – zapisuje a vrací interní poznámku produktu a poznámku prvního kupónu.

Nastav: SHOPTET_ENV_FILE (nebo proměnné), SHOPTET_TEST_PRODUCT_ID, SHOPTET_TEST_PRODUCT_CODE (kód/prefix jen tohoto produktu),
SHOPTET_TEST_PRODUCT_NAME (začátek názvu), SHOPTET_TEST_BRAND (značka produktu), volitelně SHOPTET_TEST_HIDDEN=0, pokud produkt není skrytý.
"""
import os
import server as S

PID = int(os.environ["SHOPTET_TEST_PRODUCT_ID"]); CODE = os.environ["SHOPTET_TEST_PRODUCT_CODE"]
NAME = os.environ["SHOPTET_TEST_PRODUCT_NAME"]; BRAND = os.environ["SHOPTET_TEST_BRAND"]
HIDDEN = os.environ.get("SHOPTET_TEST_HIDDEN", "1") == "1"
found = S.product_find(code=CODE)
assert [p["id"] for p in found["items"]] == [PID] and found["total"] == 1, found
assert found["items"][0]["name"].startswith(NAME) and found["items"][0]["brand"] == BRAND, found
assert S.product_find(name="nic-takoveho-neexistuje-xyz")["items"] == []
vis = S.filter_options()["visibility"]
hidden_id = next(k for k, v in vis.items() if v.startswith("Skryt")); visible_id = next(k for k, v in vis.items() if v.startswith("Viditeln"))
assert [p["id"] for p in S.product_find(code=CODE, visibility=hidden_id if HIDDEN else visible_id)["items"]] == [PID]
assert S.product_find(code=CODE, visibility=visible_id if HIDDEN else hidden_id)["items"] == []
fo = S.filter_options()
assert BRAND in fo["brand"].values() and fo["availability_sold_out"], list(fo)
try:
    S.product_find(brand="neexistujici-znacka"); assert False
except ValueError:
    pass
big = S.product_find(name=NAME.split()[0], max_pages=2)
assert big["total"] >= big["loaded"] > 0, (big["total"], big["loaded"])

p = S.product_get(PID)
f = p["fields"]
assert len(f) > 150 and "internalNote" in f and "pageId[]" in f and isinstance(f["pageId[]"], list), len(f)
assert "variantAvailabilityId[]" in p["options"] and "pageId[]" in p["options"], list(p["options"])[:20]

r = S.product_update(PID, {"internalNote": "TEST zoe check"})
assert r["diff"] == {"internalNote": {"before": f["internalNote"], "after": "TEST zoe check"}} and not r["unapplied"], r
r = S.product_update(PID, {"internalNote": f["internalNote"]})
assert r["diff"]["internalNote"]["after"] == f["internalNote"] and not r["errors"], r

n_var = len([k for k in f if k.startswith("variantAvailabilityId[")])
cur = next(v for k, v in f.items() if k.startswith("variantAvailabilityId["))
plan = S.products_bulk_update([PID], {"variantAvailabilityId[*]": "-1"}, {"variantAvailabilityId[*]": cur})
assert 0 < plan["planned_total"] <= n_var and not plan["apply"] and all(k.startswith("variantAvailabilityId[") for k in plan["report"][0]["fields"]), plan
assert S.products_bulk_update([PID], {"variantAvailabilityId[*]": "-1"}, {"variantAvailabilityId[*]": "neexistuje"})["planned_total"] == 0
r = S.products_bulk_update([PID], {"internalNote": "TEST bulk"}, apply=True)["report"][0]
assert r["applied"] == 1 and not r["unapplied"] and not r["errors"], r
r = S.products_bulk_update([PID], {"internalNote": f["internalNote"]}, apply=True)["report"][0]
assert r["applied"] == 1 and not r["unapplied"], r
sec = S.admin_sections()
assert "/admin/stranky/" in sec and "/admin/slevove-kupony/" in sec, list(sec)[:10]
pages = S.admin_list("/admin/stranky/")
assert pages["items"] and all(i["detail_path"].startswith("/admin/stranka-detail/?id=") for i in pages["items"]), pages
pg = S.admin_form_get(pages["items"][0]["detail_path"])
assert "description" in pg["fields"] and "metaDescription" in pg["fields"], list(pg["fields"])
r = S.admin_form_update(pages["items"][0]["detail_path"], {})
assert r["diff"] == {} and not r["errors"], r
cat = S.admin_list("/admin/kategorie/")["items"][0]
r = S.admin_form_update(cat["detail_path"], {})
assert r["diff"] == {} and not r["errors"], r
cp = S.admin_list("/admin/slevove-kupony/")["items"][0]
note = S.admin_form_get(cp["detail_path"], with_options=False)["fields"]["remark"]
r = S.admin_form_update(cp["detail_path"], {"remark": "TEST zoe admin_form"})
assert r["diff"] == {"remark": {"before": note, "after": "TEST zoe admin_form"}} and not r["unapplied"], r
r = S.admin_form_update(cp["detail_path"], {"remark": note})
assert not r["unapplied"] and r["diff"].get("remark", {}).get("after", note) == note, r
for bad in ["/neni-admin/", "/admin/kategorie/?action=delete&id=1"]:
    try:
        S.admin_form_get(bad); assert False
    except ValueError:
        pass
assert "error" in S.product_update(PID, {"neexistujici_pole": "x"})
assert "error" in S.product_update(PID, {"visibility": "999999"})
print("OK: find+filtry/get/update/revert/bulk/admin_list/admin_form/validace")
