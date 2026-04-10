"""
Téléchargement automatique Sentinel-2 L2A depuis Copernicus Data Space Ecosystem (CDSE)
Pour compléter les dates manquantes — California & Arkansas 2021
Usage : python download_sentinel2.py --user TON_EMAIL --password TON_MDP
"""

import argparse
import os
import time
import zipfile
from pathlib import Path

import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SAVE_DIR = Path("data/raw")

# ── Toutes les dates déjà téléchargées (batch v1 + v2) ───────────────────────
ALREADY_HAVE_TILES = {
    # Batch v1 (originales)
    "T10SGH_20210720", "T10SGH_20210126", "T10SGH_20210921",
    "T10SFG_20210126", "T10SFG_20210926", "T10SFG_20210419", "T10SFG_20210723",
    "T10SFJ_20210723", "T10SFH_20210723",
    "T15SXU_20210927", "T15SXU_20210425", "T15SXU_20210118",
    # Batch v2 (nouveaux)
    "T10SFH_20210116", "T10SFG_20210327", "T10SGH_20210419",
    "T10SFJ_20210814", "T10SFG_20210913", "T10SGH_20211016",
    "T10SGH_20210504", "T10SFH_20210511", "T10SGH_20210809",
    "T10SFH_20210911", "T10SFG_20211001", "T10SGH_20211210",
    "T15SXU_20210304", "T15SXU_20210513", "T15SXU_20210803",
    "T15SXU_20211025", "T15SXU_20211104",
}

# ── CALIFORNIA — dates manquantes ciblées (batch v3) ─────────────────────────
# DOY actuels par tuile :
#   SGH : 26,109,124,201,221,264,289,344   → manque juin(~165), nov(~308)
#   SFG : 26,86,109,204,256,269,274,289    → manque juin(~165), nov(~308), déc(~344)
#   SFH : 16,131,204,254                   → manque mars,avr,juin,oct,nov,déc
#   SFJ : 204,226                          → très peu ! jan,mars,mai,juin,sept,oct,nov,déc

TARGETS_CA = [
    # ── SGH : juin + novembre ─────────────────────────────────────────────────
    {"tile": "T10SGH", "date_start": "2021-06-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SGH", "date_start": "2021-11-01", "date_end": "2021-11-30", "max_cloud": 40},
    # ── SFG : juin + novembre + décembre ─────────────────────────────────────
    {"tile": "T10SFG", "date_start": "2021-06-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SFG", "date_start": "2021-11-01", "date_end": "2021-11-30", "max_cloud": 40},
    {"tile": "T10SFG", "date_start": "2021-12-01", "date_end": "2021-12-31", "max_cloud": 50},
    # ── SFH : mars, avril, juin, octobre, novembre, décembre ─────────────────
    {"tile": "T10SFH", "date_start": "2021-03-01", "date_end": "2021-03-31", "max_cloud": 40},
    {"tile": "T10SFH", "date_start": "2021-04-01", "date_end": "2021-04-30", "max_cloud": 30},
    {"tile": "T10SFH", "date_start": "2021-06-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SFH", "date_start": "2021-10-01", "date_end": "2021-10-31", "max_cloud": 30},
    {"tile": "T10SFH", "date_start": "2021-11-01", "date_end": "2021-11-30", "max_cloud": 40},
    {"tile": "T10SFH", "date_start": "2021-12-01", "date_end": "2021-12-31", "max_cloud": 50},
    # ── SFJ : très peu de dates — priorité haute ─────────────────────────────
    {"tile": "T10SFJ", "date_start": "2021-01-01", "date_end": "2021-01-31", "max_cloud": 50},
    {"tile": "T10SFJ", "date_start": "2021-03-01", "date_end": "2021-03-31", "max_cloud": 40},
    {"tile": "T10SFJ", "date_start": "2021-05-01", "date_end": "2021-05-31", "max_cloud": 30},
    {"tile": "T10SFJ", "date_start": "2021-06-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SFJ", "date_start": "2021-09-01", "date_end": "2021-09-30", "max_cloud": 30},
    {"tile": "T10SFJ", "date_start": "2021-10-01", "date_end": "2021-10-31", "max_cloud": 30},
    {"tile": "T10SFJ", "date_start": "2021-11-01", "date_end": "2021-11-30", "max_cloud": 40},
    {"tile": "T10SFJ", "date_start": "2021-12-01", "date_end": "2021-12-31", "max_cloud": 50},
]

# ── ARKANSAS — vide critique juin-juillet (DOY 133→215) ──────────────────────
# DOY actuels : 18, 63, 115, 133, 215, 270, 298, 308
# GAP CRITIQUE : aucune donnée entre 13 mai et 3 août
# → juin et juillet = saison de croissance maïs/soja/coton/riz

TARGETS_AR = [
    # ── PRIORITÉ ABSOLUE : juin et juillet découpés en 2 pour avoir 2 chances ─
    {"tile": "T15SXU", "date_start": "2021-06-01", "date_end": "2021-06-15", "max_cloud": 40},
    {"tile": "T15SXU", "date_start": "2021-06-16", "date_end": "2021-06-30", "max_cloud": 40},
    {"tile": "T15SXU", "date_start": "2021-07-01", "date_end": "2021-07-15", "max_cloud": 50},
    {"tile": "T15SXU", "date_start": "2021-07-16", "date_end": "2021-07-31", "max_cloud": 50},
    # ── Compléments ────────────────────────────────────────────────────────────
    {"tile": "T15SXU", "date_start": "2021-02-01", "date_end": "2021-02-28", "max_cloud": 40},
    {"tile": "T15SXU", "date_start": "2021-08-01", "date_end": "2021-08-15", "max_cloud": 50},
    {"tile": "T15SXU", "date_start": "2021-12-01", "date_end": "2021-12-31", "max_cloud": 50},
]

TARGETS_ALL = TARGETS_CA + TARGETS_AR

TOKEN_URL    = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SEARCH_URL   = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_URL = "https://zipper.dataspace.copernicus.eu/odata/v1/Products"


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

def get_token(username, password):
    resp = requests.post(TOKEN_URL, data={
        "client_id": "cdse-public",
        "grant_type": "password",
        "username": username,
        "password": password,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def maybe_refresh(username, password, token, token_time):
    if time.time() - token_time > 600:
        print("  Renouvellement du token...")
        return get_token(username, password), time.time()
    return token, token_time


# ─────────────────────────────────────────────────────────────────────────────
# RECHERCHE
# ─────────────────────────────────────────────────────────────────────────────

def search_products(tile, date_start, date_end, max_cloud):
    filter_str = (
        f"Collection/Name eq 'SENTINEL-2' "
        f"and contains(Name,'{tile}') "
        f"and contains(Name,'MSIL2A') "
        f"and ContentDate/Start gt {date_start}T00:00:00.000Z "
        f"and ContentDate/Start lt {date_end}T23:59:59.000Z"
    )
    params = {
        "$filter": filter_str,
        "$top": "20",
        "$expand": "Attributes",
        "$orderby": "ContentDate/Start asc",
    }
    resp = requests.get(SEARCH_URL, params=params, timeout=30)

    if resp.status_code == 400:
        print(f"    Filtre standard 400, essai filtre minimal...")
        filter_str = (
            f"Collection/Name eq 'SENTINEL-2' "
            f"and contains(Name,'{tile}') "
            f"and ContentDate/Start gt {date_start}T00:00:00.000Z "
            f"and ContentDate/Start lt {date_end}T23:59:59.000Z"
        )
        params["$filter"] = filter_str
        resp = requests.get(SEARCH_URL, params=params, timeout=30)

    resp.raise_for_status()
    products = resp.json().get("value", [])

    result = []
    for p in products:
        name = p.get("Name", "")
        if "MSIL2A" not in name and "S2MSI2A" not in name:
            continue
        cc = _cloud_cover(p)
        if cc <= max_cloud:
            p["_cc"] = cc
            result.append(p)

    result.sort(key=lambda x: x["_cc"])
    return result


def _cloud_cover(product):
    for attr in product.get("Attributes", []):
        if attr.get("Name") == "cloudCover":
            return float(attr.get("Value", 99))
    return 99.0


# ─────────────────────────────────────────────────────────────────────────────
# TÉLÉCHARGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def download_product(product_id, product_name, token, save_dir):
    safe_glob = list(save_dir.glob(f"*{product_name[:40]}*.SAFE"))
    if safe_glob:
        print(f"    Deja present : {safe_glob[0].name}")
        return safe_glob[0]

    zip_path = save_dir / f"{product_name}.zip"
    url      = f"{DOWNLOAD_URL}({product_id})/$value"
    headers  = {"Authorization": f"Bearer {token}"}

    print(f"    Telechargement : {product_name[:65]}...")
    try:
        with requests.get(url, headers=headers, stream=True, timeout=300) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done  = 0
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r    {100*done/total:.0f}%  ({done/1e6:.0f}/{total/1e6:.0f} MB)",
                              end="", flush=True)
        print()
        print("    Extraction...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(save_dir)
        zip_path.unlink()

        safes = list(save_dir.glob("*.SAFE"))
        return max(safes, key=os.path.getmtime) if safes else None

    except Exception as e:
        print(f"    ERREUR : {e}")
        if zip_path.exists():
            zip_path.unlink()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user",     required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--region",   choices=["ca", "ar", "all"], default="all")
    args = parser.parse_args()

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    targets = {"ca": TARGETS_CA, "ar": TARGETS_AR, "all": TARGETS_ALL}[args.region]

    print("=" * 60)
    print("  Telechargement Sentinel-2 L2A — Copernicus Data Space")
    print("=" * 60)
    print(f"  Region  : {args.region.upper()}  |  Requetes : {len(targets)}")
    print(f"  Dossier : {SAVE_DIR.resolve()}")
    print(f"  Mode    : {'DRY RUN' if args.dry_run else 'TELECHARGEMENT REEL'}\n")

    # Résumé des lacunes
    print("Lacunes a combler :")
    if args.region in ("ca", "all"):
        print("  [CA] SGH : juin, nov")
        print("  [CA] SFG : juin, nov, dec")
        print("  [CA] SFH : mars, avr, juin, oct, nov, dec")
        print("  [CA] SFJ : jan, mars, mai, juin, sept, oct, nov, dec  ← priorite haute")
    if args.region in ("ar", "all"):
        print("  [AR] SXU : JUIN + JUILLET  ← GAP CRITIQUE saison de croissance")
        print("  [AR] SXU : fev, aout, dec  ← complements")
    print()

    print("Authentification...")
    try:
        token      = get_token(args.user, args.password)
        token_time = time.time()
        print("  Token obtenu\n")
    except Exception as e:
        print(f"  ECHEC : {e}")
        return

    to_download = []

    print("Recherche des produits...")
    for t in targets:
        tile, d_s, d_e, cloud = t["tile"], t["date_start"], t["date_end"], t["max_cloud"]
        try:
            products = search_products(tile, d_s, d_e, cloud)
        except Exception as e:
            print(f"  ERREUR {tile} [{d_s[:7]}] : {e}")
            continue

        if not products:
            print(f"  AUCUN  {tile} [{d_s[5:7]}/{d_s[:4]}]  nuages<={cloud}%")
            continue

        best = products[0]
        name = best["Name"]
        cc   = best["_cc"]

        on_disk = bool(list(SAVE_DIR.glob(f"*{name[:35]}*.SAFE")))
        in_have = any(f"{tile}_{name[11:19]}" in h for h in ALREADY_HAVE_TILES)

        if on_disk or in_have:
            print(f"  [OK]   {tile} [{d_s[5:7]}/{d_s[:4]}]  nuages={cc:.0f}%  deja present  ({name[11:19]})")
        else:
            print(f"  [DL]   {tile} [{d_s[5:7]}/{d_s[:4]}]  nuages={cc:.0f}%  {name[11:19]}  → {name[:55]}...")
            to_download.append(best)

    print(f"\n{len(to_download)} nouveaux produits a telecharger")

    if args.dry_run:
        print("\n(Mode dry-run — rien telecharge)")
        if to_download:
            print("\nProduits qui seraient telecharges :")
            for p in to_download:
                print(f"  {p['Name'][11:19]}  nuages={p['_cc']:.0f}%  {p['Name'][:70]}")
        print(f"\nPour lancer :")
        print(f"  python download_sentinel2.py --user {args.user} --password *** --region {args.region}")
        return

    if not to_download:
        print("Tout est deja present — relance la cellule 4 du notebook.")
        return

    ok, fail = [], []
    for i, product in enumerate(to_download, 1):
        print(f"\n[{i}/{len(to_download)}] {product['Name'][:65]}  (nuages={product['_cc']:.0f}%)")
        token, token_time = maybe_refresh(args.user, args.password, token, token_time)
        path = download_product(product["Id"], product["Name"], token, SAVE_DIR)
        (ok if path else fail).append(product["Name"])
        if i < len(to_download):
            time.sleep(2)

    print("\n" + "=" * 60)
    print(f"  OK : {len(ok)}  |  ECHECS : {len(fail)}")
    if ok:
        print(f"\n{len(ok)} fichiers telecharges.")
        print("Relance la cellule 4 du notebook — les nouveaux .SAFE sont detectes automatiquement.")
    if fail:
        print("\nEchecs (reessaie avec max_cloud plus eleve) :")
        for n in fail:
            print(f"  {n}")


if __name__ == "__main__":
    main()