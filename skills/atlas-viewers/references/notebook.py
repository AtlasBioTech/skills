import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import requests

    import atlas_viewers as av

    return av, mo, pd, requests


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
    return ACCESSION, GENE, VARIANT, get_json


@app.cell
def _(mo):
    mo.md("""
    ## 1. La protéine (UniProt)
    """)
    return


@app.cell
def _(ACCESSION, get_json, mo):
    # Length and annotated regions come from UniProt, not from memory.
    try:
        uniprot = get_json(f"https://rest.uniprot.org/uniprotkb/{ACCESSION}.json")
    except Exception as _err:  # a failed request is shown, the notebook keeps running
        uniprot = None
        _out = mo.callout(mo.md(f"UniProt injoignable : {_err}"), kind="danger")
    else:
        _out = None
    length = uniprot["sequence"]["length"] if uniprot else 0
    # Regions worth drawing on the variant plot: domains, named regions and motifs.
    domains = [
        {
            "start": _f["location"]["start"]["value"],
            "end": _f["location"]["end"]["value"],
            "name": _f.get("description") or _f["type"],
        }
        for _f in (uniprot or {}).get("features", [])
        if _f["type"] in ("Domain", "Region", "Motif", "DNA binding", "Zinc finger")
        and not (_f.get("description") or "").startswith(("Disordered", "Interaction"))
    ]
    _out if _out is not None else mo.md(
        f"**{uniprot['proteinDescription']['recommendedName']['fullName']['value']}**, "
        f"{length} acides aminés ([{ACCESSION}](https://www.uniprot.org/uniprotkb/{ACCESSION}/entry)). "
        + "Régions : " + ", ".join(f"{d['name']} ({d['start']}–{d['end']})" for d in domains)
    )
    return domains, length


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
def _(GENE, get_json, pd):
    # ClinVar through NCBI E-utilities: esearch gives the ids, esummary the records.
    import re

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
                _rows.append(
                    {
                        "variant": f"{_AA[_match.group(1)]}{_match.group(2)}{_AA[_match.group(3)]}",
                        "position": int(_match.group(2)),
                        "significance": _germline.get("description") or "not provided",
                        "review": _germline.get("review_status", ""),
                        "clinvar_id": _uid,
                    }
                )
        clinvar_error = None
    except Exception as _err:
        clinvar_error = str(_err)
    # The same protein change can be listed on several transcripts: keep one row per change.
    clinvar = pd.DataFrame(_rows, columns=["variant", "position", "significance", "review", "clinvar_id"])
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
def _(VARIANT, av, clinvar, mo):
    # The patient's variant first, then the other changes at the same residue.
    mo.stop(clinvar.empty)
    _same_residue = clinvar[clinvar["position"] == 12].assign(_other=lambda df: df["variant"] != VARIANT)
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
def _(GENE, VARIANT, av, get_json, mo, pd):
    try:
        _found = get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            {
                "query": f'(TITLE:"{VARIANT}" OR ABSTRACT:"{VARIANT}") AND {GENE}',
                "format": "json",
                "pageSize": 8,
                "sort": "CITED desc",
                "resultType": "lite",
            },
        )
        _papers = pd.DataFrame(
            [
                {
                    "Titre": _r.get("title", ""),
                    "Revue": _r.get("journalTitle", ""),
                    "Année": _r.get("pubYear", ""),
                    "Citations": _r.get("citedByCount", 0),
                    "pmid": _r.get("pmid", ""),
                }
                for _r in _found["resultList"]["result"]
            ]
        )
        _view = av.table(
            _papers,
            links={"PubMed": "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"},
            title=f"{_found['hitCount']} articles sur {GENE} {VARIANT}, les plus cités",
        )
    except Exception as _err:
        _view = mo.callout(mo.md(f"Europe PMC injoignable : {_err}"), kind="warn")
    _view
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
