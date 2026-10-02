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
    # KRAS p.G12D : localisation, signification clinique, littérature

    Données interrogées en direct : UniProt, AlphaFold DB, ClinVar (NCBI), Europe PMC.
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

    def fetch(url, params=None, body=None):
        # GET, or POST of a JSON body (GraphQL APIs, cBioPortal). Imports kept
        # local so that no other cell's import clashes with them.
        import gzip, hashlib, json
        from datetime import datetime, timezone
        from pathlib import Path

        if body is None:
            response = requests.get(url, params=params, timeout=60, headers={"Accept": "application/json"})
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

    ACCESSION = "P01116"  # KRAS humaine, UniProt
    GENE = "KRAS"
    VARIANT = "G12D"
    RESIDUE = 12

    # An accession typed from memory can be another protein's, and every cell
    # below would then show that protein under this gene's name: check it
    # against UniProt's reviewed human entry for the gene first.
    try:
        _found = [
            hit["primaryAccession"]
            for hit in get_json(
                "https://rest.uniprot.org/uniprotkb/search",
                params={"query": f"gene_exact:{GENE} AND organism_id:9606 AND reviewed:true", "fields": "accession", "format": "json"},
            )["results"]
        ]
    except requests.RequestException:
        _found = None  # UniProt unreachable: the next cell says so
    assert _found is None or ACCESSION in _found, f"{ACCESSION} n'est pas {GENE} humaine dans UniProt ; l'accession de {GENE} est {_found}"
    return ACCESSION, GENE, RESIDUE, SAVE_RAW, VARIANT, calls, fetch, get_json


@app.cell
def _(mo):
    mo.md("""
    ## 1. La protéine (UniProt)
    """)
    return


@app.cell
def _(ACCESSION, GENE, RESIDUE, get_json, mo, re):
    # Length, regions, sites and the definition come from UniProt, not from memory.
    try:
        uniprot = get_json(f"https://rest.uniprot.org/uniprotkb/{ACCESSION}.json")
    except Exception as _err:  # a failed request is shown, the notebook keeps running
        uniprot = None
        _out = mo.callout(mo.md(f"UniProt injoignable : {_err}"), kind="danger")
    else:
        _out = None
    length = uniprot["sequence"]["length"] if uniprot else 0
    # Regions worth drawing on the variant plot: domains, named regions and motifs,
    # not the disordered stretches or the partner-binding regions ("Interaction
    # with X", "Required for interaction with Y"), which are long and would
    # cover the structural domains.
    domains = [
        {
            "start": _f["location"]["start"]["value"],
            "end": _f["location"]["end"]["value"],
            "name": _f.get("description") or _f["type"],
        }
        for _f in (uniprot or {}).get("features", [])
        if _f["type"] in ("Domain", "Region", "Motif", "DNA binding", "Zinc finger")
        and not any(_w in (_f.get("description") or "").lower() for _w in ("disordered", "interaction"))
    ]
    # Functional sites within 5 residues of the variant (ligand binding, catalytic,
    # DNA contact): what the substitution may disturb.
    sites = [
        f"{(_f.get('ligand') or {}).get('name') or _f.get('description') or _f['type']} "
        f"({_f['type'].lower()}, résidu {_f['location']['start']['value']})"
        for _f in (uniprot or {}).get("features", [])
        if _f["type"] in ("Binding site", "Active site", "Site")
        and abs(_f["location"]["start"]["value"] - RESIDUE) <= 5
    ]
    # The definition the answer gives: the gene (HGNC) and the protein (UniProt)
    # named separately, with their identifiers, and the function as UniProt's
    # curators wrote it (first sentence, PubMed citations dropped).
    definition = []
    if uniprot:
        _hgnc = next((_x["id"] for _x in uniprot.get("uniProtKBCrossReferences", []) if _x["database"] == "HGNC"), "HGNC non trouvé")
        _function = next((_c["texts"][0]["value"] for _c in uniprot.get("comments", []) if _c["commentType"] == "FUNCTION"), "")
        _function = re.split(r"(?<=\.)\s+", re.sub(r"\s*\((?:PubMed|ECO|By similarity)[^)]*\)", "", _function))[0]
        definition = [
            f"Gène {GENE} ({_hgnc}) ; protéine {uniprot['proteinDescription']['recommendedName']['fullName']['value']} "
            f"(UniProt {ACCESSION}), {length} acides aminés",
            f"Fonction (UniProt, commentaire Function) : {_function or 'non renseignée'}",
        ]
    _out if _out is not None else mo.md(
        "\n\n".join(definition)
        + f" ([fiche UniProt](https://www.uniprot.org/uniprotkb/{ACCESSION}/entry))\n\n"
        + "Régions : " + ", ".join(f"{d['name']} ({d['start']}–{d['end']})" for d in domains)
    )
    return definition, domains, length, sites


@app.cell
def _(mo):
    mo.md("""
    ## 2. Structure 3D (AlphaFold DB)

    Couleurs : confiance du modèle (pLDDT). Le résidu 12 est en magenta.
    """)
    return


@app.cell
def _(ACCESSION, av, get_json, mo):
    # The AlphaFold DB API gives the current model's URL: never hard-code a model version.
    try:
        _model = get_json(f"https://alphafold.ebi.ac.uk/api/prediction/{ACCESSION}")[0]
        _view = av.structure(
            _model["cifUrl"],
            highlight=[12],
            labels={12: "G12D"},
            color_by="plddt",
            title="KRAS · modèle AlphaFold",
            subtitle=_model["entryId"],
        )
    except Exception as _err:
        _view = mo.callout(mo.md(f"Modèle AlphaFold indisponible : {_err}"), kind="warn")
    _view
    return


@app.cell
def _(mo):
    mo.md("""
    ## 3. Variants connus (ClinVar)
    """)
    return


@app.cell
def _(GENE, get_json, pd, re):
    # ClinVar through NCBI E-utilities: esearch gives the ids, esummary the records.
    _EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    _AA = {
        "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E",
        "Gly": "G", "His": "H", "Ile": "I", "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F",
        "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
    }
    _PROTEIN_CHANGE = re.compile(r"\(p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})\)")

    _rows = []
    try:
        _ids = get_json(
            f"{_EUTILS}/esearch.fcgi",
            {
                "db": "clinvar",
                "term": f"{GENE}[gene] AND single_gene[prop] AND missense_variant[molecular_consequence]",
                "retmax": 5000,
                "retmode": "json",
            },
        )["esearchresult"]["idlist"]
        for _start in range(0, len(_ids), 400):  # esummary takes a few hundred ids per call
            _result = get_json(
                f"{_EUTILS}/esummary.fcgi",
                {"db": "clinvar", "id": ",".join(_ids[_start : _start + 400]), "retmode": "json"},
            )["result"]
            for _uid in _result["uids"]:
                _record = _result[_uid]
                _match = _PROTEIN_CHANGE.search(_record["title"])
                if not _match or _match.group(1) not in _AA or _match.group(3) not in _AA:
                    continue
                _germline = _record.get("germline_classification") or {}
                _conditions = {_t["trait_name"] for _t in _germline.get("trait_set", []) if _t.get("trait_name")}
                _rows.append(
                    {
                        "variant": f"{_AA[_match.group(1)]}{_match.group(2)}{_AA[_match.group(3)]}",
                        "position": int(_match.group(2)),
                        "significance": _germline.get("description") or "not provided",
                        "review": _germline.get("review_status", ""),
                        "conditions": "; ".join(sorted(_conditions - {"not provided"})),
                        "clinvar_id": _uid,
                    }
                )
        clinvar_error = None
    except Exception as _err:
        clinvar_error = str(_err)
    # The same protein change can be listed on several transcripts: keep one row per change.
    clinvar = pd.DataFrame(_rows, columns=["variant", "position", "significance", "review", "conditions", "clinvar_id"])
    clinvar = clinvar.drop_duplicates("variant").sort_values("position").reset_index(drop=True)
    return clinvar, clinvar_error


@app.cell
def _(av, clinvar, clinvar_error, domains, length, mo):
    # av.variants reads the columns position, label and significance; `label=` renames one.
    mo.stop(clinvar_error is not None, mo.callout(mo.md(f"ClinVar injoignable : {clinvar_error}"), kind="danger"))
    av.variants(
        clinvar,
        label="variant",
        length=length,
        domains=domains,
        highlight=[12],
        labels={12: "G12D"},
        title=f"Variants faux-sens de KRAS dans ClinVar ({len(clinvar)})",
    )
    return


@app.cell
def _(RESIDUE, VARIANT, av, clinvar, mo):
    # The patient's variant first, then the other changes at the same residue.
    mo.stop(clinvar.empty)
    _same_residue = clinvar[clinvar["position"] == RESIDUE].assign(_other=lambda df: df["variant"] != VARIANT)
    av.table(
        _same_residue.sort_values("_other").drop(columns="_other"),
        links={"ClinVar": "https://www.ncbi.nlm.nih.gov/clinvar/variation/{clinvar_id}/"},
        title="Variants ClinVar en position 12",
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## 4. Littérature (Europe PMC)
    """)
    return


@app.cell
def _(GENE, VARIANT, get_json, pd, re, requests):
    # A title is not evidence: keep each paper's abstract and, for the
    # open-access ones, the full text's results and discussion. "lu" says
    # which of the three the excerpt comes from, so the answer can say what
    # was read and quote the sentence a claim rests on.
    import xml.etree.ElementTree as ET
    from concurrent.futures import ThreadPoolExecutor

    _EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    _SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

    def _clean(text):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()

    def _excerpt(text, conclusion=True):
        # The first sentences naming the variant and, for an abstract, its
        # last one (the conclusion): what the paper did and what it found.
        _sentences = _SENTENCE.split(text)
        _picked = [_s for _s in _sentences if VARIANT in _s][: 1 if conclusion else 2]
        if conclusion and _sentences and _sentences[-1] not in _picked:
            _picked.append(_sentences[-1])
        return " […] ".join(_picked)[:600]

    def _full_text(pmcid):
        # Results and discussion sections of an open-access article; "" when
        # it cannot be had quickly (the abstract is used instead).
        try:
            # Not get_json: asked for JSON, Europe PMC refuses the XML (406).
            _response = requests.get(f"{_EPMC}/{pmcid}/fullTextXML", timeout=20)
            _response.raise_for_status()
            _body = ET.fromstring(_response.content).find("body")
        except (requests.RequestException, ET.ParseError):
            return ""
        def _prose(node):
            # Text without the figures and tables, which JATS may nest in a paragraph.
            return (node.text or "") + "".join(
                ("" if _c.tag in ("fig", "table-wrap") else _prose(_c)) + (_c.tail or "") for _c in node
            )

        def _paragraphs(sec):
            # The section's own paragraphs and its subsections'.
            for _child in sec:
                if _child.tag == "p":
                    yield _prose(_child)
                elif _child.tag == "sec":
                    yield from _paragraphs(_child)

        _sections = [
            _sec for _sec in (_body.findall("sec") if _body is not None else [])
            if re.search(r"result|discussion", f"{_sec.get('sec-type', '')} {_sec.findtext('title') or ''}", re.I)
        ]
        return _clean(" ".join(_p for _sec in _sections for _p in _paragraphs(_sec)))

    papers, literature_count, literature_error = pd.DataFrame(), None, None
    try:
        _found = get_json(
            f"{_EPMC}/search",
            {
                "query": f'(TITLE:"{VARIANT}" OR ABSTRACT:"{VARIANT}") AND {GENE}',
                "format": "json",
                "pageSize": 8,
                "sort": "CITED desc",
                "resultType": "core",  # "lite" has no abstract
            },
        )
        literature_count = int(_found["hitCount"])
        _hits = _found["resultList"]["result"]
        # Only open-access articles have their full text in Europe PMC (the
        # others answer with an error after seconds); fetched in parallel,
        # ~5 s each, at most the 8 papers above.
        _open = [_r["pmcid"] for _r in _hits if _r.get("isOpenAccess") == "Y" and _r.get("pmcid")]
        with ThreadPoolExecutor(max_workers=4) as _pool:
            _bodies = dict(zip(_open, _pool.map(_full_text, _open)))
        _rows = []
        for _r in _hits:
            _abstract, _body = _clean(_r.get("abstractText")), _bodies.get(_r.get("pmcid"), "")
            _lu = "texte intégral" if _body else "résumé" if _abstract else "titre"
            _rows.append(
                {
                    "Titre": _clean(_r.get("title")),
                    "Premier auteur": (_r.get("authorString") or "").split(",")[0],
                    "Revue": _r.get("journalInfo", {}).get("journal", {}).get("isoabbreviation", ""),
                    "Année": _r.get("pubYear", ""),
                    "Citations": _r.get("citedByCount", 0),
                    "lu": _lu,
                    "Extrait": (_excerpt(_body, conclusion=False) if _body else "") or _excerpt(_abstract),
                    "pmid": _r.get("pmid", ""),
                }
            )
        papers = pd.DataFrame(_rows)
    except Exception as _err:
        literature_error = str(_err)
    return literature_count, literature_error, papers


@app.cell
def _(GENE, VARIANT, av, literature_count, literature_error, mo, papers):
    mo.stop(literature_error is not None, mo.callout(mo.md(f"Europe PMC injoignable : {literature_error}"), kind="warn"))
    mo.vstack([
        mo.md(
            f"**{literature_count} articles** sur {GENE} {VARIANT}, les plus cités. « lu » dit ce qui a été lu "
            "de chacun (titre, résumé, texte intégral en accès libre) ; l'extrait cite les phrases qui nomment le variant "
            "(et la conclusion, pour un résumé)."
        ),
        av.table(
            papers,
            links={"PubMed": "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"},
            title=f"Littérature sur {GENE} {VARIANT} (Europe PMC)",
        ),
    ])
    return


@app.cell
def _(RESIDUE, VARIANT, clinvar, definition, domains, literature_count, mo, papers, sites):
    # The facts the answer rests on, computed from the data above. Printed as
    # well: `python notebook.py` then shows them to whoever checks the notebook.
    _domain = next((d for d in domains if d["start"] <= RESIDUE <= d["end"]), None)
    _ours = clinvar[clinvar["variant"] == VARIANT]
    _pathogenic = clinvar["significance"].str.contains("athogenic", na=False) & ~clinvar["significance"].str.contains("onflicting|enign", na=False)
    _at_residue = int((_pathogenic & (clinvar["position"] == RESIDUE)).sum())
    facts = [
        *definition,
        f"Région : {_domain['name']} ({_domain['start']}–{_domain['end']})" if _domain else "Région : aucune région annotée",
        f"Sites fonctionnels à ±5 résidus (UniProt) : {', '.join(sites) or 'aucun'}",
        (
            f"ClinVar {VARIANT} : {_ours.iloc[0]['significance']} ({_ours.iloc[0]['review']}), "
            f"variation {_ours.iloc[0]['clinvar_id']}, pour : {_ours.iloc[0]['conditions'][:300] or 'non précisé'}"
            if len(_ours)
            else f"ClinVar {VARIANT} : absent de la recherche"
        ),
        f"Variants pathogènes en position {RESIDUE} : {_at_residue} (point chaud mutationnel si plusieurs)",
        f"Articles (Europe PMC) : {literature_count if literature_count is not None else 'non disponible'}",
    ]
    # What each paper says, and how much of it was read: the answer cites
    # these excerpts, never a title alone.
    for _p in papers.to_dict("records"):
        facts.append(
            f"PMID {_p['pmid']} ({_p['Premier auteur']} et al., {_p['Revue']}, {_p['Année']}) — lu : {_p['lu']} — "
            f"{_p['Titre']} — extrait : {_p['Extrait'] or '(aucun)'}"
        )
    print("\n".join(facts))
    mo.md("## Résumé des données\n\n" + "\n".join(f"- {f}" for f in facts))
    return


@app.cell
def _(mo):
    mo.md("""
    ## Sources

    UniProt P01116 · AlphaFold DB AF-P01116-F1 · ClinVar (NCBI E-utilities) · Europe PMC.
    """)
    return


@app.cell
def _(SAVE_RAW, av, calls, clinvar, definition, mo, papers, pd, re, requests):
    # « Provenance »: which release of each source answered, the exact request,
    # when. The data cells' outputs (clinvar, definition, papers) are arguments
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
