import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import re

    import marimo as mo
    import pandas as pd
    import requests

    import atlas_viewers as av

    return av, mo, pd, re, requests


@app.cell
def _(mo):
    mo.md("""
    # TP53 p.R175H : population, tumeurs, actionnabilité, structures

    Sources complémentaires de `notebook.py`, interrogées en direct, sans clé :
    gnomAD, cBioPortal, CIViC, RCSB PDB, UniProt (le résidu), NCI TP53 Database.
    """)
    return


@app.cell
def _(mo, requests):
    # One helper for every public API: a timeout, an error that says which URL
    # failed, and provenance. Each request is logged in `calls` (exact URL and
    # body, UTC time, HTTP status, the release the response states) and its raw
    # response saved, gzipped, to provenance/<date>/ next to the notebook (one
    # file per distinct request and day: a re-run the same day overwrites it).
    # The last cell shows the log as the « Provenance » table.
    calls = []
    SAVE_RAW = True

    def fetch(url, params=None, body=None, accept="application/json"):
        # GET, or POST of a JSON body (GraphQL APIs, cBioPortal); `accept` for a
        # non-JSON answer (Europe PMC full text is XML). Imports kept
        # local so that no other cell's import clashes with them.
        import gzip, hashlib, json
        from datetime import datetime, timezone
        from pathlib import Path

        if body is None:
            response = requests.get(url, params=params, timeout=60, headers={"Accept": accept})
        else:
            response = requests.post(url, params=params, json=body, timeout=120)
        when = datetime.now(timezone.utc)
        host = response.url.split("/")[2]
        raw = ""
        if SAVE_RAW and response.ok:
            _key = hashlib.sha1(f"{response.url} {json.dumps(body, sort_keys=True)}".encode()).hexdigest()[:12]
            raw = f"provenance/{when:%Y-%m-%d}/{host}-{_key}.gz"
            _path = Path(mo.notebook_dir() or ".") / raw
            _path.parent.mkdir(parents=True, exist_ok=True)
            _path.write_bytes(gzip.compress(response.content))
        # The release, when the response itself states it (UniProt in a header,
        # AlphaFold DB in the model record); the last cell asks the others.
        release = ""
        if "X-UniProt-Release" in response.headers:
            release = f"UniProtKB {response.headers['X-UniProt-Release']} ({response.headers.get('X-UniProt-Release-Date', '')})"
        elif host == "alphafold.ebi.ac.uk" and response.ok:
            _model = response.json()[0]
            release = f"modèle v{_model['latestVersion']} du {_model['modelCreatedDate'][:10]}"
        calls.append({"url": response.url, "body": body, "date": f"{when:%Y-%m-%dT%H:%M:%SZ}",
                      "status": response.status_code, "release": release, "raw": raw})
        response.raise_for_status()
        return response

    def get_json(url, params=None, body=None):
        return fetch(url, params, body).json()

    # Same names as notebook.py, so that the cells below can be pasted into a
    # notebook built from it.
    ACCESSION = "P04637"  # TP53 humaine, UniProt (notebook.py checks the accession)
    GENE = "TP53"
    VARIANT = "R175H"
    RESIDUE = 175
    return ACCESSION, GENE, RESIDUE, SAVE_RAW, VARIANT, calls, fetch, get_json


@app.cell
def _(mo):
    mo.md("""
    ## A. Fréquence dans la population (gnomAD)
    """)
    return


@app.cell
def _(GENE, VARIANT, get_json, mo):
    # gnomAD v4 (GraphQL, open, no key): how often the variant is seen in
    # ~800,000 people, exomes and genomes. The gene's variants are fetched and
    # matched on the protein change (HGVS p. on the canonical transcript), so
    # no genomic coordinate has to be typed.
    _AA3 = dict(zip("ACDEFGHIKLMNPQRSTVWY", "Ala Cys Asp Glu Phe Gly His Ile Lys Leu Met Asn Pro Gln Arg Ser Thr Val Trp Tyr".split()))
    _hgvsp = f"p.{_AA3[VARIANT[0]]}{VARIANT[1:-1]}{_AA3[VARIANT[-1]]}"
    _query = f"""{{ gene(gene_symbol: "{GENE}", reference_genome: GRCh38) {{ variants(dataset: gnomad_r4) {{
        variant_id hgvsp exome {{ ac an homozygote_count filters }} genome {{ ac an homozygote_count filters }} }} }} }}"""
    try:
        _variants = get_json("https://gnomad.broadinstitute.org/api", body={"query": _query})["data"]["gene"]["variants"]
        gnomad_facts = []
        for _v in (_v for _v in _variants if _v["hgvsp"] == _hgvsp):  # one per nucleotide change
            _sets = {_name: _v[_n] for _n, _name in (("exome", "exomes"), ("genome", "génomes")) if _v[_n]}
            _ac, _an = sum(_s["ac"] for _s in _sets.values()), sum(_s["an"] for _s in _sets.values())
            gnomad_facts.append(
                f"gnomAD v4 {_hgvsp} ({_v['variant_id']}) : {_ac} allèles sur {_an} (fréquence {_ac / _an:.1e}), "
                f"{sum(_s['homozygote_count'] for _s in _sets.values())} homozygote(s) ; "
                + " ; ".join(f"{_n} {_s['ac']}/{_s['an']}" + (f" (filtres : {', '.join(_s['filters'])})" if _s["filters"] else "") for _n, _s in _sets.items())
            )
        gnomad_facts = gnomad_facts or [f"gnomAD v4 {_hgvsp} : absent ({len(_variants)} variants de {GENE} dans gnomAD)"]
        _out = mo.md("\n\n".join(gnomad_facts))
    except Exception as _err:
        gnomad_facts, _out = [f"gnomAD : non interrogé ({_err})"], mo.callout(mo.md(f"gnomAD injoignable : {_err}"), kind="warn")
    _out
    return (gnomad_facts,)


@app.cell
def _(mo):
    mo.md("""
    ## B. Fréquence dans les tumeurs (cBioPortal)
    """)
    return


@app.cell
def _(GENE, VARIANT, av, get_json, mo, pd):
    # cBioPortal (REST, open, no key): how often the variant is found in
    # tumours, in one fixed public cohort so that the count can be re-run and
    # compared: TCGA PanCancer Atlas (32 studies). Denominator: the samples
    # sequenced for mutations in each study, not all samples.
    _API = "https://www.cbioportal.org/api"
    try:
        _studies = {_s["studyId"]: _s["name"] for _s in get_json(f"{_API}/studies", {"keyword": "tcga_pan_can_atlas_2018"})}
        _lists = get_json(f"{_API}/sample-lists/fetch", {"projection": "DETAILED"}, body=[f"{_s}_sequenced" for _s in _studies])
        _sequenced = {_l["studyId"]: len(_l["sampleIds"]) for _l in _lists}
        _gene_id = get_json(f"{_API}/genes/{GENE}")["entrezGeneId"]
        _muts = pd.DataFrame(get_json(
            f"{_API}/mutations/fetch", {"projection": "SUMMARY"},
            body={"entrezGeneIds": [_gene_id], "molecularProfileIds": [f"{_s}_mutations" for _s in _studies]},
        ))
        _by_study = lambda df: df.groupby("studyId")["sampleId"].nunique()
        cbio = pd.DataFrame({"séquencés": _sequenced, f"{GENE} muté": _by_study(_muts),
                             VARIANT: _by_study(_muts[_muts["proteinChange"] == VARIANT])}).fillna(0).astype(int)
        cbio[f"% {VARIANT}"] = (100 * cbio[VARIANT] / cbio["séquencés"]).round(1)
        cbio = cbio.rename(index=_studies).rename_axis("étude").reset_index().sort_values(VARIANT, ascending=False)
        _n, _total = int(cbio[VARIANT].sum()), int(cbio["séquencés"].sum())
        _rank = int(_muts.groupby("proteinChange")["sampleId"].nunique().rank(ascending=False, method="min").get(VARIANT, 0))
        cbio_facts = [
            f"cBioPortal, TCGA PanCancer Atlas ({len(cbio)} études, {_total} tumeurs séquencées) : {VARIANT} dans {_n} tumeurs "
            f"({_n / _total:.1%}) ; {GENE} muté dans {int(cbio[f'{GENE} muté'].sum())} ({cbio[f'{GENE} muté'].sum() / _total:.1%})"
            + (f" ; {VARIANT} est le changement de {GENE} n° {_rank} par nombre de tumeurs" if _rank else ""),
        ]
        if _n:
            cbio_facts.append(f"{VARIANT} le plus fréquent dans : " + ", ".join(
                f"{_r['étude']} {_r[VARIANT]}/{_r['séquencés']} ({_r[f'% {VARIANT}']} %)" for _r in cbio.head(3).to_dict("records") if _r[VARIANT]
            ))
        _out = mo.vstack([mo.md("\n\n".join(cbio_facts)), av.table(cbio, title=f"{GENE} {VARIANT} dans TCGA PanCancer Atlas (cBioPortal)")])
    except Exception as _err:
        cbio_facts, _out = [f"cBioPortal : non interrogé ({_err})"], mo.callout(mo.md(f"cBioPortal injoignable : {_err}"), kind="warn")
    _out
    return (cbio_facts,)


@app.cell
def _(mo):
    mo.md("""
    ## C. Actionnabilité (CIViC)
    """)
    return


@app.cell
def _(GENE, VARIANT, av, get_json, mo, pd):
    # CIViC (GraphQL, open, no key, CC0): curated clinical evidence for the
    # variant, alone or in a combined molecular profile: predictive (response
    # to a therapy), prognostic, diagnostic… Levels: A validated, B clinical,
    # C case study, D preclinical, E inferential. OncoKB needs a licence: not used.
    _query = """query($name: String) { evidenceItems(molecularProfileName: $name, status: ACCEPTED, first: 100) { nodes {
        id evidenceType evidenceLevel evidenceDirection significance disease { name } therapies { name }
        source { citationId sourceType } molecularProfile { name } } } }"""
    _FR = {
        "predictive": "prédictive", "prognostic": "pronostique", "diagnostic": "diagnostique", "predisposing": "prédisposition",
        "oncogenic": "oncogène", "functional": "fonctionnelle", "supports": "soutient", "does_not_support": "ne soutient pas",
        "sensitivityresponse": "sensibilité/réponse", "resistance": "résistance", "poor_outcome": "pronostic défavorable",
        "better_outcome": "pronostic favorable", "positive": "positive", "negative": "négative", "dominant_negative": "dominant négatif",
    }
    _fr = lambda value: _FR.get(value.lower(), value.lower().replace("_", " "))
    try:
        _items = get_json("https://civicdb.org/api/graphql", body={"query": _query, "variables": {"name": f"{GENE} {VARIANT}"}})["data"]["evidenceItems"]["nodes"]
        civic = pd.DataFrame([{
            "eid": str(_i["id"]), "niveau": _i["evidenceLevel"], "type": _fr(_i["evidenceType"]), "profil": _i["molecularProfile"]["name"],
            "sens": _fr(_i["evidenceDirection"]), "signification": _fr(_i["significance"]),
            "maladie": (_i["disease"] or {}).get("name", ""), "traitements": ", ".join(_t["name"] for _t in _i["therapies"]),
            "pmid": _i["source"]["citationId"] if _i["source"]["sourceType"] == "PUBMED" else "",
        } for _i in _items], columns=["eid", "niveau", "type", "profil", "sens", "signification", "maladie", "traitements", "pmid"]).sort_values(["niveau", "type"])
        civic_facts = [
            f"CIViC : {len(civic)} preuves acceptées pour {GENE} {VARIANT} ({(civic['profil'] != f'{GENE} {VARIANT}').sum()} dans un profil combiné) ; "
            f"par type : {', '.join(f'{_k} {_v}' for _k, _v in civic['type'].value_counts().items()) or 'aucune'} ; "
            f"par niveau : {', '.join(f'{_k} {_v}' for _k, _v in civic['niveau'].value_counts().sort_index().items()) or 'aucun'}",
            *(f"CIViC EID{_r['eid']} (niveau {_r['niveau']}, {_r['type']}, {_r['profil']}) : {_r['sens']} {_r['signification']}, "
              f"{_r['maladie']}{', ' + _r['traitements'] if _r['traitements'] else ''} (PMID {_r['pmid'] or '—'})"
              for _r in civic[civic["niveau"].isin(["A", "B"])].head(5).to_dict("records")),
        ]
        _out = mo.vstack([mo.md(civic_facts[0]), av.table(
            civic, links={"eid": "https://civicdb.org/evidence/{eid}/summary", "pmid": "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"},
            title=f"Preuves CIViC pour {GENE} {VARIANT}",
        )])
    except Exception as _err:
        civic_facts, _out = [f"CIViC : non interrogé ({_err})"], mo.callout(mo.md(f"CIViC injoignable : {_err}"), kind="warn")
    _out
    return (civic_facts,)


@app.cell
def _(mo):
    mo.md("""
    ## D. Structures expérimentales (RCSB PDB)
    """)
    return


@app.cell
def _(ACCESSION, RESIDUE, VARIANT, av, get_json, mo, pd, re):
    # RCSB PDB (search and GraphQL data APIs, open, no key): the experimental
    # structures of the protein, which cover the residue and which carry the
    # variant itself (declared mutation or title), with method, resolution,
    # ligands (chemical component ids) and partner molecules.
    _node = lambda attr, value: {"type": "terminal", "service": "text", "parameters": {
        "attribute": f"rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.{attr}", "operator": "exact_match", "value": value}}
    _search = {"query": {"type": "group", "logical_operator": "and", "nodes": [_node("database_accession", ACCESSION), _node("database_name", "UniProt")]},
               "return_type": "entry", "request_options": {"return_all_hits": True}}
    _query = """query($ids: [String!]!) { entries(entry_ids: $ids) { rcsb_id struct { title } exptl { method }
        rcsb_entry_info { resolution_combined } rcsb_accession_info { initial_release_date }
        polymer_entities { rcsb_polymer_entity { pdbx_description pdbx_mutation }
          rcsb_polymer_entity_align { reference_database_accession aligned_regions { ref_beg_seq_id length } } }
        nonpolymer_entities { nonpolymer_comp { chem_comp { id } } } } }"""

    def _row(e):
        _ours = [_p for _p in e["polymer_entities"] if any(_a["reference_database_accession"] == ACCESSION for _a in _p["rcsb_polymer_entity_align"] or [])]
        _regions = [_r for _p in _ours for _a in _p["rcsb_polymer_entity_align"] if _a["reference_database_accession"] == ACCESSION for _r in _a["aligned_regions"]]
        _mutations = " ".join(_p["rcsb_polymer_entity"]["pdbx_mutation"] or "" for _p in _ours)
        return {
            "pdb": e["rcsb_id"], "méthode": ", ".join(_x["method"].lower() for _x in e["exptl"] or []),
            "résolution (Å)": (e["rcsb_entry_info"]["resolution_combined"] or [None])[0],
            f"couvre {RESIDUE}": any(_r["ref_beg_seq_id"] <= RESIDUE < _r["ref_beg_seq_id"] + _r["length"] for _r in _regions),
            # A 9-residue peptide in an MHC groove also "covers" the residue: say how much of the protein is there.
            "résidus": ", ".join(f"{_r['ref_beg_seq_id']}–{_r['ref_beg_seq_id'] + _r['length'] - 1}" for _r in _regions),
            "longueur": sum(_r["length"] for _r in _regions),
            f"porte {VARIANT}": bool(re.search(rf"\b{VARIANT}\b", f"{_mutations} {e['struct']['title']}")),
            "ligands": ", ".join(sorted({_c["nonpolymer_comp"]["chem_comp"]["id"] for _c in e["nonpolymer_entities"] or []})),
            "partenaires": "; ".join(sorted({_p["rcsb_polymer_entity"]["pdbx_description"][:40] for _p in e["polymer_entities"] if _p not in _ours})),
            "titre": e["struct"]["title"], "publiée": e["rcsb_accession_info"]["initial_release_date"][:10],
        }

    try:
        _ids = [_h["identifier"] for _h in get_json("https://search.rcsb.org/rcsbsearch/v2/query", body=_search)["result_set"]]
        _all = pd.DataFrame([_row(_e) for _e in get_json("https://data.rcsb.org/graphql", body={"query": _query, "variables": {"ids": _ids}})["data"]["entries"]])
        pdb = _all[_all[f"couvre {RESIDUE}"]].sort_values([f"porte {VARIANT}", "résolution (Å)"], ascending=[False, True])
        _best = pdb[pdb["méthode"].str.contains("x-ray|electron", na=False) & (pdb["longueur"] >= 50)].sort_values("résolution (Å)").head(3)
        _carrying = pdb[pdb[f"porte {VARIANT}"]]
        pdb_facts = [
            f"PDB : {len(_all)} structures expérimentales de {ACCESSION}, dont {len(pdb)} couvrent le résidu {RESIDUE} "
            f"et {len(_carrying)} portent {VARIANT}" + (" : " + " ; ".join(
                f"{_r['pdb']} (résidus {_r['résidus']}, {_r['méthode']}, partenaires {_r['partenaires'] or 'aucun'})" for _r in _carrying.head(5).to_dict("records")
            ) if len(_carrying) else ""),
            "Meilleures résolutions couvrant le résidu (≥ 50 résidus de la protéine) : " + " ; ".join(
                f"{_r['pdb']} (résidus {_r['résidus']}, {_r['méthode']}, {_r['résolution (Å)']} Å, ligands {_r['ligands'] or 'aucun'}, partenaires {_r['partenaires'] or 'aucun'})"
                for _r in _best.to_dict("records")
            ),
        ]
        _out = mo.vstack([mo.md("\n\n".join(pdb_facts)), av.table(
            pdb.drop(columns=f"couvre {RESIDUE}"), links={"pdb": "https://www.rcsb.org/structure/{pdb}"}, title=f"Structures PDB couvrant le résidu {RESIDUE}",
        )])
    except Exception as _err:
        pdb_facts, _out = [f"PDB : non interrogé ({_err})"], mo.callout(mo.md(f"RCSB PDB injoignable : {_err}"), kind="warn")
    _out
    return (pdb_facts,)


@app.cell
def _(mo):
    mo.md("""
    ## E. Le résidu dans UniProt et dans la base TP53 du NCI
    """)
    return


@app.cell
def _(ACCESSION, RESIDUE, get_json, mo):
    # UniProt's curated annotations of this very position: natural variants
    # (with the disease) and mutagenesis experiments (with the effect).
    try:
        _features = get_json(f"https://rest.uniprot.org/uniprotkb/{ACCESSION}.json", {"fields": "ft_variant,ft_mutagen"}).get("features", [])
        residue_facts = [
            f"UniProt {_f['type'].lower()} au résidu {RESIDUE} : "
            f"{_f['alternativeSequence'].get('originalSequence', '')}→{'/'.join(_f['alternativeSequence'].get('alternativeSequences', []))} — {_f.get('description', '')}"
            for _f in _features
            if _f["location"]["start"]["value"] == RESIDUE == _f["location"]["end"]["value"]
        ] or [f"UniProt : aucun variant naturel ni mutagenèse annotés au résidu {RESIDUE}"]
        _out = mo.md("\n\n".join(f"- {_l}" for _l in residue_facts))
    except Exception as _err:
        residue_facts, _out = [f"UniProt (résidu) : non interrogé ({_err})"], mo.callout(mo.md(f"UniProt injoignable : {_err}"), kind="warn")
    _out
    return (residue_facts,)


@app.cell
def _(GENE, VARIANT, fetch, mo, pd):
    # NCI TP53 Database, for TP53 only. It has no API, but publishes open,
    # versioned release files; MutationView (r21, 9 MB) has one row per
    # nucleotide change: functional class (yeast transactivation assays),
    # dominant-negative activity, hotspot, tumour count, structural context.
    from io import StringIO as _StringIO

    tp53db_facts = []
    if GENE == "TP53":
        try:
            _table = pd.read_csv(_StringIO(fetch("https://tp53.cancer.gov/static/data/MutationView_r21.csv").text), low_memory=False)
            _rows = _table[_table["ProtDescription"] == f"p.{VARIANT}"]
            _r = _rows.sort_values("TCGA_ICGC_GENIE_count", ascending=False).iloc[0]
            tp53db_facts = [
                f"NCI TP53 Database r21 {VARIANT} : transactivation {_r['TransactivationClass']}, classe dominant négatif / perte de fonction {_r['DNE_LOFclass']}, "
                f"point chaud {_r['Hotspot']}, {_r['Domain_function']} / {_r['Structural_motif']}, résidu {_r['Residue_function']} ; "
                f"tumeurs (TCGA, ICGC, GENIE) : {int(_rows['TCGA_ICGC_GENIE_count'].sum())}"
            ]
            _out = mo.md(tp53db_facts[0])
        except Exception as _err:
            tp53db_facts, _out = [f"NCI TP53 Database : non lue ({_err})"], mo.callout(mo.md(f"NCI TP53 Database injoignable : {_err}"), kind="warn")
    else:
        _out = None
    _out
    return (tp53db_facts,)


@app.cell
def _(cbio_facts, civic_facts, gnomad_facts, mo, pdb_facts, residue_facts, tp53db_facts):
    facts = []
    # Complementary sources (gnomAD, cBioPortal, CIViC, PDB, UniProt residue,
    # NCI TP53): in a notebook built from notebook.py, paste this block into
    # its facts cell, after the existing list.
    facts += [*gnomad_facts, *cbio_facts, *civic_facts, *pdb_facts, *residue_facts, *tp53db_facts]
    print("\n".join(facts))
    mo.md("## Résumé des données\n\n" + "\n".join(f"- {f}" for f in facts))
    return


@app.cell
def _(SAVE_RAW, av, calls, cbio_facts, civic_facts, gnomad_facts, mo, pd, pdb_facts, re, requests, residue_facts, tp53db_facts):
    # « Provenance »: which release of each source answered, the exact request,
    # when. The data cells' outputs (*_facts) are arguments
    # only so that this cell runs after them. It knows every source the
    # atlas-viewers and clinical-trials references use: copy it as is.
    import json as _json
    from pathlib import Path as _Path
    from urllib.parse import parse_qs as _parse_qs, unquote_plus as _unquote_plus, urlsplit as _urlsplit

    _NAMES = {
        "rest.uniprot.org": "UniProt", "alphafold.ebi.ac.uk": "AlphaFold DB", "eutils.ncbi.nlm.nih.gov": "NCBI",
        "www.ebi.ac.uk": "Europe PMC", "clinicaltrials.gov": "ClinicalTrials.gov", "gnomad.broadinstitute.org": "gnomAD",
        "www.cbioportal.org": "cBioPortal", "civicdb.org": "CIViC", "search.rcsb.org": "RCSB PDB",
        "data.rcsb.org": "RCSB PDB", "tp53.cancer.gov": "NCI TP53 Database",
    }

    def _release(host, call):
        # The release a source states elsewhere than in its response, or the
        # fact that it publishes none.
        def _get(url, **params):
            return requests.get(url, params=params, timeout=30).json()
        if host == "eutils.ncbi.nlm.nih.gov":  # ClinVar, PubMed…: einfo gives the build and last update
            _db = _parse_qs(_urlsplit(call["url"]).query)["db"][0]
            _i = _get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi", db=_db, retmode="json")["einforesult"]["dbinfo"][0]
            return f"{_i['menuname']} {_i['dbbuild']}, mise à jour {_i['lastupdate']}"
        if host == "clinicaltrials.gov":
            return "API {apiVersion}, données du {dataTimestamp}".format(**_get("https://clinicaltrials.gov/api/v2/version"))
        if host == "www.cbioportal.org":
            return "portail {portalVersion}, base {dbVersion}".format(**_get("https://www.cbioportal.org/api/info"))
        if host == "civicdb.org":
            _r = requests.post("https://civicdb.org/api/graphql", json={"query": "{ dataReleases { name } }"}, timeout=30).json()
            return "base en direct ; dernière publication mensuelle " + next(
                _d["name"] for _d in _r["data"]["dataReleases"] if _d["name"] != "nightly")
        if host == "gnomad.broadinstitute.org":
            return "jeu de données " + re.search(r"dataset: (\w+)", call["body"]["query"]).group(1)
        if host == "tp53.cancer.gov":
            return "publication " + re.search(r"_(r\d+)\.csv", call["url"]).group(1)
        return {
            "www.ebi.ac.uk": "aucune version des données publiée (index mis à jour chaque jour)",
            "search.rcsb.org": "aucune version publiée (archive mise à jour chaque semaine)",
            "data.rcsb.org": "aucune version publiée (archive mise à jour chaque semaine)",
        }.get(host, "non publiée par l'API")

    _releases, _rows = {}, []
    for _c in calls:
        _host = _c["url"].split("/")[2]
        _key = (_host, str(_parse_qs(_urlsplit(_c["url"]).query).get("db")))  # one ask per source (per NCBI database)
        if not _c["release"] and _key not in _releases:
            try:
                _releases[_key] = _release(_host, _c)
            except Exception as _err:
                _releases[_key] = f"non obtenue ({_err})"
        # Shown decoded, with spaces to wrap on, and not as a bare URL (the table
        # would show it as a link named after the site); exact in requests.json.
        _url = _unquote_plus(_c["url"]).replace("&", " & ").replace(",", ", ")
        _query = f"POST {_url} {_json.dumps(_c['body'], ensure_ascii=False)}" if _c["body"] else f"GET {_url}"
        _rows.append({
            "source": _NAMES.get(_host, _host), "version": _c["release"] or _releases[_key],
            "requête": _query if len(_query) < 700 else _query[:700] + "… (complète dans requests.json)",
            "date (UTC)": _c["date"], "statut HTTP": _c["status"], "réponse brute": _c["raw"],
        })
    # A cell re-run in the editor logs its requests again: keep the last of each.
    _provenance = pd.DataFrame(_rows, columns=["source", "version", "requête", "date (UTC)", "statut HTTP", "réponse brute"]).drop_duplicates("requête", keep="last")
    # The complete log (full URLs and bodies) next to the raw responses.
    if SAVE_RAW and any(_c["raw"] for _c in calls):
        _dir = _Path(mo.notebook_dir() or ".") / _Path(next(_c["raw"] for _c in reversed(calls) if _c["raw"])).parent
        (_dir / "requests.json").write_text(_json.dumps(calls, ensure_ascii=False, indent=1))
    for _s in _provenance.groupby(["source", "version"], sort=False).agg(n=("requête", "size"), date=("date (UTC)", "max")).reset_index().itertuples():
        print(f"Provenance : {_s.source} — version : {_s.version} — {_s.n} requête(s), la dernière le {_s.date}")
    mo.vstack([
        mo.md(
            "## Provenance\n\nChaque requête de ce notebook : source, version, requête, date. "
            "Les réponses brutes sont enregistrées (gzip) dans `provenance/<date>/`, avec `requests.json`, "
            "le journal complet des requêtes exactes."
        ),
        av.table(_provenance, title="Provenance des données"),
    ])
    return


if __name__ == "__main__":
    app.run()
