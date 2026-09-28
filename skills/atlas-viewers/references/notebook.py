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
def _(requests):
    # One helper for every public API: a timeout, and an error that says which URL failed.
    def get_json(url, params=None):
        response = requests.get(url, params=params, timeout=60, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()

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
    return ACCESSION, GENE, RESIDUE, VARIANT, get_json


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


if __name__ == "__main__":
    app.run()
