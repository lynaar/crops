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

ALREADY_HAVE_TILES = {
    "T10SGH_20210720", "T10SGH_20210126", "T10SGH_20210921",
    "T10SFG_20210126", "T10SFG_20210926", "T10SFG_20210419", "T10SFG_20210723",
    "T10SFJ_20210723", "T10SFH_20210723",
    "T15SXU_20210927", "T15SXU_20210425", "T15SXU_20210118",
}

TARGETS_CA = [
    {"tile": "T10SGH", "date_start": "2021-03-01", "date_end": "2021-04-30", "max_cloud": 30},
    {"tile": "T10SGH", "date_start": "2021-05-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SGH", "date_start": "2021-08-01", "date_end": "2021-09-15", "max_cloud": 30},
    {"tile": "T10SGH", "date_start": "2021-10-01", "date_end": "2021-11-30", "max_cloud": 30},
    {"tile": "T10SGH", "date_start": "2021-12-01", "date_end": "2021-12-31", "max_cloud": 50},
    {"tile": "T10SFG", "date_start": "2021-03-01", "date_end": "2021-04-15", "max_cloud": 30},
    {"tile": "T10SFG", "date_start": "2021-05-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SFG", "date_start": "2021-08-01", "date_end": "2021-09-15", "max_cloud": 30},
    {"tile": "T10SFG", "date_start": "2021-10-01", "date_end": "2021-11-30", "max_cloud": 40},
    {"tile": "T10SFH", "date_start": "2021-01-01", "date_end": "2021-03-31", "max_cloud": 40},
    {"tile": "T10SFH", "date_start": "2021-04-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SFH", "date_start": "2021-08-01", "date_end": "2021-10-31", "max_cloud": 30},
    {"tile": "T10SFJ", "date_start": "2021-01-01", "date_end": "2021-03-31", "max_cloud": 40},
    {"tile": "T10SFJ", "date_start": "2021-04-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T10SFJ", "date_start": "2021-08-01", "date_end": "2021-10-31", "max_cloud": 30},
]

TARGETS_AR = [
    {"tile": "T15SXU", "date_start": "2021-02-01", "date_end": "2021-03-31", "max_cloud": 40},
    {"tile": "T15SXU", "date_start": "2021-05-01", "date_end": "2021-06-30", "max_cloud": 30},
    {"tile": "T15SXU", "date_start": "2021-07-01", "date_end": "2021-08-31", "max_cloud": 40},
    {"tile": "T15SXU", "date_start": "2021-10-01", "date_end": "2021-11-30", "max_cloud": 30},
    {"tile": "T15SXU", "date_start": "2021-11-01", "date_end": "2021-12-31", "max_cloud": 40},
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
# RECHERCHE — filtre OData minimal (fix 400 Bad Request)
# Le bug venait du $orderby avec any() non supporté par CDSE.
# On utilise un filtre simple + tri Python local.
# ─────────────────────────────────────────────────────────────────────────────

def search_products(tile, date_start, date_end, max_cloud):
    # Filtre simplifié : pas de $orderby complexe, pas de OData.CSC.Intersects
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
        # Dernier recours : filtre ultra-minimal
        print(f"    ⚠️  Filtre standard 400, essai filtre minimal...")
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

    # Filtrer L2A et couverture nuageuse côté Python
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
            print(f"  AUCUN  {tile} [{d_s[:7]}->{d_e[:7]}]  (essayez max_cloud={cloud+20}%)")
            continue

        best = products[0]
        name = best["Name"]
        cc   = best["_cc"]

        # Vérifier si déjà présent sur disque ou dans ALREADY_HAVE
        on_disk  = bool(list(SAVE_DIR.glob(f"*{name[:35]}*.SAFE")))
        in_have  = any(f"{tile}_{name[11:19]}" in h for h in ALREADY_HAVE_TILES)

        if on_disk or in_have:
            print(f"  [OK]   {tile} [{d_s[:7]}]  nuages={cc:.0f}%  deja present")
        else:
            print(f"  [DL]   {tile} [{d_s[:7]}]  nuages={cc:.0f}%  → {name[:55]}...")
            to_download.append(best)

    print(f"\n{len(to_download)} nouveaux produits a telecharger")

    if args.dry_run:
        print("\n(Mode dry-run — rien telecharge)")
        if to_download:
            print("\nProduits qui seraient telecharges :")
            for p in to_download:
                print(f"  {p['Name'][:70]}")
        print(f"\nPour lancer : python download_sentinel2.py --user {args.user} --password *** --region {args.region}")
        return

    if not to_download:
        print("Tout est deja present.")
        return

    ok, fail = [], []
    for i, product in enumerate(to_download, 1):
        print(f"\n[{i}/{len(to_download)}] {product['Name'][:65]}")
        token, token_time = maybe_refresh(args.user, args.password, token, token_time)
        path = download_product(product["Id"], product["Name"], token, SAVE_DIR)
        (ok if path else fail).append(product["Name"])
        if i < len(to_download):
            time.sleep(2)

    print("\n" + "=" * 60)
    print(f"  OK : {len(ok)}  |  ECHECS : {len(fail)}")
    if ok:
        print("\nTelecharges :")
        for n in ok:
            print(f"  {n}")
    if fail:
        print("\nEchecs :")
        for n in fail:
            print(f"  {n}")

    print("""
======================================================
  SUITE : mettre a jour DATES_MAP dans le notebook
======================================================
  Pour chaque nouveau .SAFE telecharge, ajouter dans
  DATES_MAP_CA ou DATES_MAP_AR :

  'nom_date': (
      'NOM_FICHIER.SAFE',
      'L2A_TXXX_...',       # dossier dans .SAFE/GRANULE/
      'TXXX_YYYYMMDDTXXXXXX',  # prefixe des bandes jp2
      'SGH',                   # zone : SGH / SFH / SFG / SFJ / SXU
  ),
""")


if __name__ == "__main__":
    main()

# pip install requests
#python download_sentinel2.py --user ton@email.com --password TON_MDP --dry-run
# D'abord l'Arkansas (seulement 4 dates → priorité absolue)
#python download_sentinel2.py --user ton@email.com --password TON_MDP --region ar
# Ensuite la California
#python download_sentinel2.py --user ton@email.com --password TON_MDP --region ca    