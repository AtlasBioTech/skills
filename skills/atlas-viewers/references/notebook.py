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
def _(GENE, VARIANT, mo):
    # Every string the reader sees is built from GENE, VARIANT, RESIDUE and
    # ACCESSION: change those four and nothing else names the example's gene.
    mo.md(f"""
    # {GENE} p.{VARIANT} : localisation, signification clinique, littérature

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
    # Functional sites (ligand or metal binding, catalytic, DNA contact): the
    # 3D cell below keeps those that touch the variant's residue in space.
    site_features = [
        {
            "start": _f["location"]["start"]["value"],
            "end": _f["location"]["end"]["value"],
            "name": f"{(_f.get('ligand') or {}).get('name') or _f.get('description') or _f['type']} "
            f"({_f['type'].lower()}, résidu {_f['location']['start']['value']})",
        }
        for _f in (uniprot or {}).get("features", [])
        if _f["type"] in ("Binding site", "Active site", "Site")
    ]
    # The residue UniProt has at the variant's position: it must be the variant's
    # reference amino acid, or the numbering is another isoform's.
    reference_residue = uniprot["sequence"]["value"][RESIDUE - 1] if uniprot and RESIDUE <= length else "?"
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
    return definition, domains, length, reference_residue, site_features


@app.cell
def _(RESIDUE, mo):
    mo.md(f"""
    ## 2. Structure 3D (AlphaFold DB)

    Couleurs : confiance du modèle (pLDDT). Le résidu {RESIDUE} est en magenta.
    """)
    return


@app.cell
def _(ACCESSION, GENE, RESIDUE, VARIANT, av, get_json, mo):
    # The AlphaFold DB API gives the current model's URL: never hard-code a model version.
    try:
        _model = get_json(f"https://alphafold.ebi.ac.uk/api/prediction/{ACCESSION}")[0]
        _view = av.structure(
            _model["cifUrl"],
            highlight=[RESIDUE],
            labels={RESIDUE: VARIANT},
            color_by="plddt",
            title=f"{GENE} · modèle AlphaFold",
            subtitle=_model["entryId"],
        )
    except Exception as _err:
        _view = mo.callout(mo.md(f"Modèle AlphaFold indisponible : {_err}"), kind="warn")
    _view
    return


@app.cell
def _(ACCESSION, RESIDUE, get_json, mo, requests, site_features):
    # The variant's neighbourhood in space, not in sequence: TP53 R175 touches
    # the zinc ligands C238 and C242, 60 residues away. Neighbours are the
    # residues with an atom within 8 Å of an atom of the variant's residue, in
    # the AlphaFold model (PDB format: fixed columns, pLDDT in the B-factor).
    # A neighbourhood is only as good as the model there: pLDDT goes with it.
    # TODO: colour the view above by domain when av.structure takes domains=
    # (workbench PR #83, not merged yet).
    _CUTOFF = 8.0
    try:
        _pdb = requests.get(get_json(f"https://alphafold.ebi.ac.uk/api/prediction/{ACCESSION}")[0]["pdbUrl"], timeout=60)
        _pdb.raise_for_status()
        _atoms = [
            (int(_l[22:26]), float(_l[30:38]), float(_l[38:46]), float(_l[46:54]), float(_l[60:66]))
            for _l in _pdb.text.splitlines()
            if _l.startswith("ATOM")
        ]
    except Exception as _err:
        _atoms, _error = [], str(_err)
    else:
        _error = None
    _plddt = {_a[0]: _a[4] for _a in _atoms}  # the same value on every atom of a residue
    _mine = [_a for _a in _atoms if _a[0] == RESIDUE]
    _near = {
        _a[0]
        for _a in _atoms
        if _a[0] != RESIDUE and any((_a[1] - _b[1]) ** 2 + (_a[2] - _b[2]) ** 2 + (_a[3] - _b[3]) ** 2 <= _CUTOFF**2 for _b in _mine)
    }
    _sites = [_s["name"] for _s in site_features if any(_r in _near | {RESIDUE} for _r in range(_s["start"], _s["end"] + 1))]
    # A low-confidence neighbour's position is not information (AlphaFold places
    # disordered stretches anywhere): named apart.
    _shaky = sorted(_r for _r in _near if _plddt[_r] < 70)

    def _confidence(value):  # AlphaFold DB's bands
        return "très haute" if value > 90 else "confiante" if value > 70 else "faible" if value > 50 else "très faible"

    if _mine:
        _here, _mean = _plddt[RESIDUE], sum(_plddt.values()) / len(_plddt)
        structure_facts = [
            f"Confiance du modèle AlphaFold : pLDDT {_here:.0f} au résidu {RESIDUE} ({_confidence(_here)}), "
            f"moyenne {_mean:.1f} sur la protéine, {sum(_v > 70 for _v in _plddt.values()) / len(_plddt):.0%} des résidus au-dessus de 70",
            f"Voisins 3D du résidu {RESIDUE} (un atome à moins de {_CUTOFF:.0f} Å, modèle AlphaFold) : "
            + (", ".join(map(str, sorted(_near))) or "aucun")
            + (f" ; dont pLDDT < 70, position peu fiable : {', '.join(map(str, _shaky))}" if _shaky else ""),
            f"Sites fonctionnels UniProt au résidu {RESIDUE} ou parmi ses voisins 3D : {', '.join(_sites) or 'aucun'}"
            + ("" if _here > 70 else " (voisinage peu fiable : pLDDT faible à ce résidu)"),
        ]
    else:
        structure_facts = [f"Voisinage 3D du résidu {RESIDUE} : non calculé ({_error or 'résidu absent du modèle'})"]
    mo.callout(mo.md("\n\n".join(structure_facts)), kind="info" if _mine and _here > 70 else "warn")
    return (structure_facts,)


@app.cell
def _(mo):
    mo.md("""
    ## 3. Variants connus (ClinVar)
    """)
    return


@app.cell
def _(GENE, get_json, mo, pd, re):
    # ClinVar through NCBI E-utilities: esearch gives the ids, esummary the records.
    # No `single_gene[prop]` filter: ClinVar lists a second gene on many records
    # (BRCA1's exon 11 overlaps LOC126862571) and that filter dropped them all,
    # leaving BRCA1 residues 1072-1365 empty. The title's gene is checked instead.
    _EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    _AA = {
        "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E",
        "Gly": "G", "His": "H", "Ile": "I", "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F",
        "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
    }
    # "NM_000546.6(TP53):c.524G>A (p.Arg175His)": transcript, gene, c. and p. changes.
    _TITLE = re.compile(r"^(N[MR]_\d+)\.\d+\(([^)]+)\):(c\.\S+) \(p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})\)$")

    clinvar_records, _count = {}, None
    try:
        _ids = []
        while _count is None or len(_ids) < _count:  # page through every id, 5,000 at a time
            _page = get_json(
                f"{_EUTILS}/esearch.fcgi",
                {
                    "db": "clinvar",
                    "term": f"{GENE}[gene] AND missense_variant[molecular_consequence]",
                    "retstart": len(_ids),
                    "retmax": 5000,
                    "retmode": "json",
                },
            )["esearchresult"]
            _count = int(_page["count"])
            if not _page["idlist"]:
                break
            _ids += _page["idlist"]
        for _start in range(0, len(_ids), 400):  # esummary takes a few hundred ids per call
            _result = get_json(
                f"{_EUTILS}/esummary.fcgi",
                {"db": "clinvar", "id": ",".join(_ids[_start : _start + 400]), "retmode": "json"},
            )["result"]
            clinvar_records.update({_uid: _result[_uid] for _uid in _result["uids"]})
        clinvar_error = None
    except Exception as _err:
        clinvar_error = str(_err)

    _rows = []
    for _uid, _record in clinvar_records.items():
        _m = _TITLE.match(_record["title"])
        if not _m or _m.group(2) != GENE or _m.group(4) not in _AA or _m.group(6) not in _AA:
            continue  # another gene, or not a missense change on a transcript
        # Germline and somatic (oncogenicity, clinical impact) classifications are
        # separate in ClinVar: kept apart. A record with none of the three has
        # "no classification provided" (evidence-only submissions, e.g. functional data).
        _germline = _record.get("germline_classification") or {}
        _conditions = {_t["trait_name"] for _t in _germline.get("trait_set", []) if _t.get("trait_name")}
        _rows.append(
            {
                "variant": f"{_AA[_m.group(4)]}{_m.group(5)}{_AA[_m.group(6)]}",
                "position": int(_m.group(5)),
                "hgvs_c": _record["title"].split(" (p.")[0],
                "significance": _germline.get("description") or "aucune classification germinale",
                "review": _germline.get("review_status", ""),
                "oncogenicity": (_record.get("oncogenicity_classification") or {}).get("description", ""),
                "clinical_impact": (_record.get("clinical_impact_classification") or {}).get("description", ""),
                "conditions": "; ".join(sorted(_conditions - {"not provided"})),
                "transcript": _m.group(1),
                "clinvar_id": _uid,
            }
        )
    clinvar = pd.DataFrame(_rows, columns=["variant", "position", "hgvs_c", "significance", "review", "oncogenicity", "clinical_impact", "conditions", "transcript", "clinvar_id"])
    # One transcript, so that positions are comparable: the one ClinVar names its
    # records on, the gene's MANE Select (the most frequent in the titles). Records
    # named on another one (KRAS: NM_033360, isoform 4A) number residues differently.
    # One row per ClinVar record: two records with the same protein change are
    # two nucleotide changes, both kept.
    reference_transcript = clinvar["transcript"].mode()[0] if len(clinvar) else ""
    clinvar = clinvar[clinvar["transcript"] == reference_transcript].drop(columns="transcript")
    clinvar = clinvar.sort_values("position").reset_index(drop=True)

    _somatic = (clinvar["oncogenicity"] != "") | (clinvar["clinical_impact"] != "")
    _unclassified = clinvar["significance"] == "aucune classification germinale"
    clinvar_summary = (
        f"ClinVar {GENE}, faux-sens : {_count} fiches trouvées, {len(clinvar_records)} récupérées"
        f"{'' if _count == len(clinvar_records) else ' (INCOMPLET : décomptes partiels)'} ; "
        f"{len(clinvar)} sur {reference_transcript} ({len(clinvar_records) - len(clinvar)} écartées : nommées sur un autre "
        f"transcrit ou un autre gène, ou sans changement faux-sens dans le titre) ; {int(_unclassified.sum())} sans classification germinale, dont "
        f"{int((_unclassified & _somatic).sum())} avec une classification somatique seule et "
        f"{int((_unclassified & ~_somatic).sum())} sans aucune classification (« no classification provided ») ; "
        f"{int(_somatic.sum())} avec une classification somatique (oncogénicité ou impact clinique)"
    )
    # Fail loudly: every record the search counted must have come back.
    _warning = None
    if clinvar_error is None and _count != len(clinvar_records):
        _warning = mo.callout(
            mo.md(f"**ClinVar incomplet** : {_count} fiches annoncées, {len(clinvar_records)} récupérées. Les décomptes ci-dessous sont partiels."),
            kind="danger",
        )
    _warning
    return clinvar, clinvar_error, clinvar_records, clinvar_summary, reference_transcript


@app.cell
def _(VARIANT, clinvar, clinvar_records, re, requests):
    # How solid the variant's classification is, from its ClinVar record:
    # nomenclature (HGVS c. and p. on the reference transcript, GRCh38 position),
    # review status, date, submissions, somatic classifications apart, and the
    # ACMG criteria an expert panel wrote in its comment. esummary has most of it;
    # the per-submission classifications and the panel's comment need the full
    # record (efetch, VCV XML), read for this variant only.
    import xml.etree.ElementTree as _ET

    _STARS = {
        "practice guideline": 4,
        "reviewed by expert panel": 3,
        "criteria provided, multiple submitters, no conflicts": 2,
        "criteria provided, conflicting classifications": 1,
        "criteria provided, single submitter": 1,
    }
    _ACMG = re.compile(r"\b(?:PVS1|PS[1-4]|PM[1-6]|PP[1-5]|BA1|BS[1-4]|BP[1-7])(?:_[A-Za-z]+)?\b")

    def _classification(record, key):
        _c = record.get(key) or {}
        if not _c.get("description"):
            return "aucune"
        _status = _c.get("review_status", "")
        return (
            f"{_c['description']} ({_status}, {_STARS.get(_status, 0)} étoile(s) sur 4, "
            f"dernière évaluation {_c.get('last_evaluated', '')[:10].replace('/', '-')})"
        )

    variant_facts = []
    for _uid in clinvar.loc[clinvar["variant"] == VARIANT, "clinvar_id"]:
        _record = clinvar_records[_uid]
        _set = _record["variation_set"][0]
        _loc = next((_l for _l in _set["variation_loc"] if _l["assembly_name"] == "GRCh38"), None)
        _rs = next((_x["db_id"] for _x in _set["variation_xrefs"] if _x["db_source"] == "dbSNP"), None)
        _conditions = sorted({_t["trait_name"] for _t in (_record.get("germline_classification") or {}).get("trait_set", [])} - {"not provided"})
        variant_facts += [
            f"Nomenclature ({VARIANT}, ClinVar {_uid}) : {_record['title']} ; "
            + (f"GRCh38 chr{_loc['chr']}:{_loc['start']}" if _loc else "GRCh38 : non renseigné")
            + f" (SPDI {_set.get('canonical_spdi') or 'non renseigné'})"
            + (f" ; dbSNP rs{_rs}" if _rs else ""),
            f"ClinVar {VARIANT}, classification germinale : {_classification(_record, 'germline_classification')} ; "
            f"pour : {'; '.join(_conditions)[:300] or 'non précisé'}",
            f"ClinVar {VARIANT}, classifications somatiques : oncogénicité {_classification(_record, 'oncogenicity_classification')} ; "
            f"impact clinique {_classification(_record, 'clinical_impact_classification')}",
        ]
        try:
            _xml = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params={"db": "clinvar", "id": _uid, "rettype": "vcv", "is_variationid": ""},
                timeout=60,
            )
            _xml.raise_for_status()
            _assertions = list(_ET.fromstring(_xml.content).iter("ClinicalAssertion"))
        except (requests.RequestException, _ET.ParseError) as _err:
            variant_facts.append(f"ClinVar {VARIANT}, soumissions : détail indisponible ({_err})")
            continue
        # Each submission's own classification (several per submitter is possible).
        _counts = {}
        for _a in _assertions:
            for _c in _a.iterfind("Classification/*"):
                if _c.tag in ("GermlineClassification", "OncogenicityClassification", "SomaticClinicalImpact"):
                    _text, _germline = (_c.text or "").strip(), _c.tag.startswith("Germline")
                    _key = f"{_text.capitalize() if _germline else _text} ({'germinal' if _germline else 'somatique'})"
                    _counts[_key] = _counts.get(_key, 0) + 1
        _panel = [
            _a
            for _a in _assertions
            if _a.findtext("Classification/ReviewStatus") in ("reviewed by expert panel", "practice guideline")
        ]
        _criteria = list(dict.fromkeys(_ACMG.findall(" ".join(_a.findtext("Classification/Comment") or "" for _a in _panel))))
        variant_facts += [
            f"ClinVar {VARIANT}, soumissions : {len(_assertions)} — "
            + ", ".join(f"{_n} {_k}" for _k, _n in sorted(_counts.items(), key=lambda _kv: -_kv[1]))
            + ("" if "onflicting" not in (_record.get("germline_classification") or {}).get("description", "") else " (conflit déclaré par ClinVar)"),
            (
                f"ClinVar {VARIANT}, critères ACMG du panel d'experts "
                f"({', '.join(_a.find('ClinVarAccession').get('SubmitterName', '') for _a in _panel)}) : "
                f"{', '.join(_criteria) or 'non lisibles dans son commentaire'}"
                if _panel
                else f"ClinVar {VARIANT}, critères ACMG : pas de panel d'experts ; ceux des laboratoires ne sont pas structurés dans ClinVar"
            ),
            f"ClinVar {VARIANT}, non disponible ici : le détail des tests fonctionnels (seuls les critères PS3/BS3 ci-dessus les signalent ; "
            f"commentaires des soumissions sur https://www.ncbi.nlm.nih.gov/clinvar/variation/{_uid}/)",
        ]
    return (variant_facts,)


@app.cell
def _(GENE, RESIDUE, VARIANT, av, clinvar, clinvar_error, domains, length, mo, reference_transcript):
    # av.variants reads the columns position, label and significance; `label=` renames one.
    mo.stop(clinvar_error is not None, mo.callout(mo.md(f"ClinVar injoignable : {clinvar_error}"), kind="danger"))
    av.variants(
        clinvar,
        label="variant",
        length=length,
        domains=domains,
        highlight=[RESIDUE],
        labels={RESIDUE: VARIANT},
        title=f"Variants faux-sens de {GENE} dans ClinVar ({len(clinvar)}, {reference_transcript})",
    )
    return


@app.cell
def _(RESIDUE, VARIANT, av, clinvar, mo):
    # The patient's variant first, then the other changes at the same residue;
    # the HGVS c. name tells apart two nucleotide changes giving the same protein
    # change, and the somatic classifications sit beside the germline one.
    mo.stop(clinvar.empty)
    _same_residue = clinvar[clinvar["position"] == RESIDUE].assign(_other=lambda df: df["variant"] != VARIANT)
    av.table(
        _same_residue.sort_values("_other").drop(columns="_other"),
        links={"ClinVar": "https://www.ncbi.nlm.nih.gov/clinvar/variation/{clinvar_id}/"},
        columns=["variant", "hgvs_c", "significance", "review", "oncogenicity", "clinical_impact", "conditions", "ClinVar"],
        title=f"Variants ClinVar en position {RESIDUE}",
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
def _(
    RESIDUE,
    VARIANT,
    clinvar,
    clinvar_summary,
    definition,
    domains,
    literature_count,
    mo,
    papers,
    reference_residue,
    structure_facts,
    variant_facts,
):
    # The facts the answer rests on, computed from the data above. Printed as
    # well: `python notebook.py` then shows them to whoever checks the notebook.
    _domain = next((d for d in domains if d["start"] <= RESIDUE <= d["end"]), None)
    facts = [
        *definition,
        f"Région : {_domain['name']} ({_domain['start']}–{_domain['end']})" if _domain else "Région : aucune région annotée",
        f"Articles (Europe PMC) : {literature_count if literature_count is not None else 'non disponible'}",
    ]
    # Variant, ClinVar and 3D neighbourhood. The count at the residue is only
    # that: a mutational hotspot is somatic recurrence in tumours (COSMIC,
    # cancerhotspots.org), which this notebook does not query.
    _pathogenic = clinvar["significance"].str.contains("athogenic", na=False) & ~clinvar["significance"].str.contains("onflicting|enign", na=False)
    _here = clinvar[_pathogenic & (clinvar["position"] == RESIDUE)]
    facts += [
        f"Résidu {RESIDUE} dans UniProt : {reference_residue}"
        + ("" if reference_residue == VARIANT[0] else f" — DIFFÉRENT de la référence du variant {VARIANT} : numérotation d'une autre isoforme ?"),
        *structure_facts,
        *(variant_facts or [f"ClinVar {VARIANT} : absent de la recherche"]),
        clinvar_summary,
        f"Variants pathogènes ClinVar à cette position (classification germinale pathogène ou probablement pathogène) : "
        f"{len(_here)}{' — ' + ', '.join(_here['variant']) if len(_here) else ''}",
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
def _(ACCESSION, mo, reference_transcript):
    mo.md(f"""
    ## Sources

    UniProt {ACCESSION} · AlphaFold DB AF-{ACCESSION}-F1 · ClinVar (NCBI E-utilities, transcrit {reference_transcript}) · Europe PMC.
    """)
    return


if __name__ == "__main__":
    app.run()
