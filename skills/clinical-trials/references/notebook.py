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
    # Inhibiteurs de PARP dans le cancer de l'ovaire : essais cliniques récents

    Données interrogées en direct : ClinicalTrials.gov (registre des essais) et
    Europe PMC (résultats publiés).
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

    # The question, as registry search terms (English: both registries index in English).
    CONDITION = "ovarian cancer"
    INTERVENTION = "PARP inhibitor OR olaparib OR niraparib OR rucaparib OR talazoparib OR senaparib"
    SINCE = "2021-01-01"  # "récents": trials running at some point since then, publications since then
    # For the literature: the drugs or the target in the title or abstract, the disease in the title.
    PAPERS_QUERY = (
        '(ABSTRACT:"PARP inhibitor" OR TITLE:olaparib OR TITLE:niraparib OR TITLE:rucaparib) '
        'AND (TITLE:ovarian OR TITLE:ovary)'
    )
    return CONDITION, INTERVENTION, PAPERS_QUERY, SAVE_RAW, SINCE, calls, fetch, get_json


@app.cell
def _(mo):
    mo.md("""
    ## 1. Les essais enregistrés (ClinicalTrials.gov)
    """)
    return


@app.cell
def _(INTERVENTION, get_json, mo, re):
    # Every name each searched drug goes by, found at run time, not typed in:
    # its development codes from ChEMBL (sotorasib = AMG 510), added to the
    # registry search (a trial may give only "JDQ443") and to the counts below.
    # Codes only (letters then digits): synonym lists also hold words naming
    # another drug ("bicalutamide" for talazoparib in ChEMBL).
    def norm(name):  # "AMG-510", "AMG 510" and "amg510" are one code
        return re.sub(r"[^a-z0-9]", "", name.lower())

    def drug_codes(names):
        return {n for n in names if re.fullmatch(r"[a-z]{1,6}\d{3,}", norm(n))}

    drugs = [d.strip() for d in INTERVENTION.split(" OR ") if " " not in d.strip()]
    chembl_codes = {d: set() for d in drugs}
    try:
        _chembl = get_json(
            "https://www.ebi.ac.uk/chembl/api/data/molecule.json",
            {"pref_name__in": ",".join(d.upper() for d in drugs), "only": "pref_name,molecule_synonyms", "limit": 1000},
        )
        for _m in _chembl["molecules"]:
            for _d in (d for d in drugs if d.upper() == _m["pref_name"]):
                chembl_codes[_d] |= drug_codes(s["molecule_synonym"] for s in _m.get("molecule_synonyms") or [])
        synonyms_error = None
    except Exception as _err:  # without ChEMBL, the registry names alone
        synonyms_error = str(_err)
    # One spelling per code for the search ("AMG-510" finds "AMG 510" too)
    SEARCH_TERMS = " OR ".join([INTERVENTION, *{norm(c): c for cs in chembl_codes.values() for c in sorted(cs)}.values()])
    mo.callout(mo.md(f"ChEMBL injoignable, synonymes du registre seulement : {synonyms_error}"), kind="warn") if synonyms_error else None
    return SEARCH_TERMS, chembl_codes, drug_codes, drugs, norm


@app.cell
def _(CONDITION, SEARCH_TERMS, SINCE, get_json, pd, re):
    # ClinicalTrials.gov API v2, every page: the counts below need the whole set.
    # "Recent" = running at some point since SINCE (completion date after it, or
    # none yet), whatever the start: a start-date filter drops the pivotal trials
    # that started earlier and publish now (CodeBreaK 100, KRYSTAL-1).
    _fields = ",".join([
        "NCTId", "Acronym", "BriefTitle", "StudyType", "OverallStatus", "WhyStopped", "Phase",
        "StartDate", "CompletionDate", "LeadSponsorName", "EnrollmentInfo", "HasResults",
        "ArmsInterventionsModule", "ReferencesModule",
    ])
    _params = {
        "query.cond": CONDITION,
        "query.intr": SEARCH_TERMS,
        "filter.advanced": f"AREA[CompletionDate]RANGE[{SINCE},MAX] OR AREA[CompletionDate]MISSING",
        "fields": _fields,
        "sort": "StartDate:desc",
        "pageSize": 200,
        "countTotal": "true",
    }
    _studies, trials_total, trials_error = [], 0, None
    try:
        while len(_studies) < 1000:  # 5 pages at most; the text says so if more exist
            _page = get_json("https://clinicaltrials.gov/api/v2/studies", _params)
            _studies += _page["studies"]
            trials_total = _page.get("totalCount", trials_total)
            if not _page.get("nextPageToken"):
                break
            _params["pageToken"] = _page["nextPageToken"]
    except Exception as _err:  # a failed request is shown, the notebook keeps running
        trials_error = str(_err)

    def _names(i):  # an intervention as registered: its name and its other names
        return [i["name"], *i.get("otherNames", [])]

    # One function reads every registry field the notebook uses: the cell is
    # long, but each column's source is in one place.
    def _row(study):
        p = study["protocolSection"]
        design, status = p.get("designModule", {}), p.get("statusModule", {})
        arms = p.get("armsInterventionsModule", {})
        # Experimental arms only: a drug given as the comparator is not "tested".
        # Trials whose arms carry no type (old records) count every intervention.
        _exp = {a["label"] for a in arms.get("armGroups", []) if a.get("type") == "EXPERIMENTAL"}
        _typed = any(a.get("type") for a in arms.get("armGroups", []))
        _ints = arms.get("interventions", [])
        exp = [i for i in _ints if not _typed or _exp & set(i.get("armGroupLabels", []))]
        enrolment = design.get("enrollmentInfo", {})
        return {
            "nct": p["identificationModule"]["nctId"],
            "titre": " — ".join(filter(None, [p["identificationModule"].get("acronym"), p["identificationModule"].get("briefTitle", "")])),
            "type": design.get("studyType", ""),
            # ["PHASE1", "PHASE2"] -> "Phase 1/Phase 2"; "NA" (not applicable: device, procedure) -> "n/a"
            "phase": "/".join(ph.replace("EARLY_PHASE", "Phase précoce ").replace("PHASE", "Phase ") for ph in design.get("phases", []) if ph != "NA") or "n/a",
            "statut": status.get("overallStatus", ""),
            "motif d'arrêt": status.get("whyStopped", ""),
            "début": status.get("startDateStruct", {}).get("date", ""),
            "fin": status.get("completionDateStruct", {}).get("date", ""),
            "promoteur": p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", ""),
            # ACTUAL once enrolment is over, else the planned number (ESTIMATED)
            "effectif": f"{enrolment['count']} ({'réel' if enrolment.get('type') == 'ACTUAL' else 'prévu'})" if "count" in enrolment else "",
            "bras expérimentaux": "; ".join(i["name"] for i in exp),
            "comparateurs": "; ".join(i["name"] for i in _ints if i not in exp),
            "résultats au registre": "oui" if study.get("hasResults") else "non",
            # Not shown: names used to count drugs, PMIDs the registry links to the trial
            "_exp_names": [n for i in exp for n in _names(i)],
            "_all_names": [_names(i) for i in _ints],
            # RESULT (given by the sponsor) and DERIVED (PubMed records giving the
            # NCT id) references, published after the start: some sponsors file
            # their background reading as RESULT.
            "_pmids": [
                r["pmid"] for r in p.get("referencesModule", {}).get("references", [])
                if r.get("pmid") and r.get("type") in ("RESULT", "DERIVED")
                and max(re.findall(r"\b(?:19|20)\d\d\b", r.get("citation", "")), default="9999") >= status.get("startDateStruct", {}).get("date", "")[:4]
            ],
        }

    # The columns come from an empty row, so a failed request still gives them
    trials = pd.DataFrame([_row(s) for s in _studies], columns=list(_row({"protocolSection": {"identificationModule": {"nctId": ""}}})))
    # ONE set for every count, table and fact below. Observational studies and
    # withdrawn trials (never enrolled anyone) are listed apart, not counted.
    scope = trials[(trials["type"] == "INTERVENTIONAL") & (trials["statut"] != "WITHDRAWN")]
    excluded = trials.drop(scope.index)
    SCOPE_TEXT = f"essais interventionnels, hors retirés, en cours ou terminés depuis {SINCE[:4]}"
    return SCOPE_TEXT, excluded, scope, trials, trials_error, trials_total


@app.cell
def _(SCOPE_TEXT, av, excluded, mo, scope, trials, trials_error, trials_total):
    mo.stop(trials_error is not None, mo.callout(mo.md(f"ClinicalTrials.gov injoignable : {trials_error}"), kind="danger"))
    _kind = {"WITHDRAWN": "retiré", "OBSERVATIONAL": "observationnelle", "EXPANDED_ACCESS": "accès élargi"}
    _apart = ", ".join(f"{r.nct} ({_kind.get(r.statut) or _kind.get(r.type, r.type)})" for r in excluded.itertuples())
    mo.vstack([
        mo.md(
            f"**{len(scope)} {SCOPE_TEXT}** (cliquez un identifiant pour la fiche de l'essai)."
            + (f" Écartés des comptes : {_apart}." if len(excluded) else "")
            + (f" Le registre en compte {trials_total} : seuls les {len(trials)} premiers sont lus." if trials_total > len(trials) else "")
        ),
        av.table(
            scope,
            links={"nct": "https://clinicaltrials.gov/study/{nct}"},
            columns=["nct", "titre", "phase", "statut", "début", "fin", "effectif", "bras expérimentaux", "comparateurs", "motif d'arrêt", "promoteur", "résultats au registre"],
            title="Essais cliniques (ClinicalTrials.gov)",
        ),
    ])
    return


@app.cell
def _(chembl_codes, drug_codes, drugs, norm, trials):
    # One step through the registry: an intervention that is one drug (named by
    # its INN or a code) and names exactly one searched drug lends it its codes
    # ("JDQ443", other name "opnurasib"); a combination ("avutometinib and
    # sotorasib", other names AMG 510, VS-6766) or a class lends none.
    aliases = {d: {norm(d)} | {norm(c) for c in chembl_codes[d]} for d in drugs}
    _extra = {d: set() for d in drugs}
    for _names in (n for names in trials["_all_names"] for n in names):
        _hit = [d for d, a in aliases.items() if {norm(x) for x in _names} & a]
        if len(_hit) == 1 and (norm(_names[0]) in aliases[_hit[0]] or drug_codes(_names[:1])):
            _extra[_hit[0]] |= {norm(c) for c in drug_codes(_names)}
    aliases = {d: aliases[d] | _extra[d] for d in drugs}
    return (aliases,)


@app.cell
def _(aliases, norm, pd, scope):
    # Which searched drugs each trial tests in an EXPERIMENTAL arm, under any of
    # their names. Every count is over `scope`, the set stated above the table.
    tested = scope["_exp_names"].map(lambda names: sorted({d for d, a in aliases.items() for n in names for x in a if x in norm(n)}))
    drug_counts = pd.DataFrame(
        [{"traitement": d, "essais": int(tested.map(lambda t: d in t).sum())} for d in aliases], columns=["traitement", "essais"]
    ).sort_values("essais", ascending=False)
    # The registry search also matches trials that only mention the drugs
    # (e.g. "after a PARP inhibitor"): on_drug marks those that give one.
    on_drug = tested.map(bool)
    phase_counts = scope["phase"].value_counts()
    status_counts = scope["statut"].value_counts()
    return drug_counts, on_drug, phase_counts, status_counts, tested


@app.cell
def _(mo):
    mo.md("""
    ## 2. Les résultats publiés (Europe PMC)
    """)
    return


@app.cell
def _(INTERVENTION, PAPERS_QUERY, SINCE, aliases, get_json, norm, pd, re):
    # Trial publications: the most cited AND the most recent (citation counts
    # alone keep only the older trials), each with how it was selected, its
    # type, and the results section of its abstract, whole.
    from html import unescape as _unescape

    # The disease as titles and results write it (change it with CONDITION):
    # a paper about another disease is set aside, even when its background or
    # methods name this one ("excluding NSCLC").
    _ABOUT = r"ovar"
    # The searched drugs as the trials cell knows them (names, ChEMBL and
    # registry codes) and the classes searched ("PARP inhibitor"): a paper
    # naming none in its title or results tests something else (a vaccine
    # given to the same patients) and is set aside too.
    _DRUGS = {a for names in aliases.values() for a in names} | {norm(c) for c in INTERVENTION.split(" OR ") if " " in c.strip()}
    _query = (
        f"{PAPERS_QUERY} AND (PUB_TYPE:\"Clinical Trial\" OR PUB_TYPE:\"Randomized Controlled Trial\" "
        f"OR PUB_TYPE:\"Clinical Trial, Phase III\" OR PUB_TYPE:\"Clinical Trial, Phase II\") "
        f"AND FIRST_PDATE:[{SINCE} TO 3000-01-01]"
    )

    def _clean(text):
        # Tags out after unescaping (titles escape theirs), but not "p<0.001".
        return re.sub(r"\s+", " ", re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*[^<>]*>", " ", _unescape(text or ""))).strip()

    def _sections(abstract):
        # Europe PMC marks a structured abstract's sections with <h4>; older
        # records write "RESULTS:" inline. [] when the abstract has no sections.
        parts = re.split(r"<h4>(.*?)</h4>", abstract or "")
        if len(parts) == 1:
            parts = re.split(r"\b(BACKGROUND|OBJECTIVES?|METHODS|RESULTS|FINDINGS|CONCLUSIONS?|INTERPRETATION)\s*:", abstract or "")
        return [(_clean(parts[i]), _clean(parts[i + 1])) for i in range(1, len(parts) - 1, 2)]

    def _type(r):
        # From Europe PMC's pubTypeList, and the title or abstract for what it does not tag.
        types = " ".join((r.get("pubTypeList") or {}).get("pubType", [])).lower()
        text = f"{r.get('title', '')} {r.get('abstractText', '')}".lower()
        if re.search(r"news|comment|editorial|letter", types):
            return "commentaire / news"
        if re.search(r"matching-adjusted|indirect (treatment )?comparison", text):
            return "comparaison indirecte (MAIC)"
        if re.search(r"meta-analysis|systematic", types) or "meta-analysis" in text:
            return "méta-analyse"
        if "pooled analysis" in text:
            return "analyse poolée"
        if "protocol" in types or re.search(r"\bprotocol\b|study design|rationale and design", r.get("title", "").lower()):
            return "protocole"
        return "essai" if re.search(r"clinical trial|randomized", types) else "autre article"

    def _row(r, selection):
        sections, abstract = _sections(r.get("abstractText")), _clean(r.get("abstractText"))
        results = " ".join(t for h, t in sections if re.match(r"results?|findings", h, re.I))
        kind = _type(r)
        if results:
            read = "section Résultats"
        elif sections or not abstract or kind in ("commentaire / news", "protocole"):
            # No results section (a protocol, a comment): say so rather than
            # show the background as if it were results.
            read = "pas de résultats dans le résumé" if abstract else "pas de résumé"
        else:
            results, read = abstract, "résumé entier (non structuré)"
        return {
            "pmid": r.get("pmid", ""),
            "titre": _clean(r.get("title")),
            "type": kind,
            "sélection": selection,
            "revue": r.get("journalInfo", {}).get("journal", {}).get("title", ""),
            "année": r.get("pubYear", ""),
            "citations": r.get("citedByCount", 0),
            "premier auteur": (r.get("authorString") or "").split(",")[0],
            "résultats lus": read,
            "résultats (résumé)": results,
            # About the disease: in the title or the results, not in the background or the
            # methods, which may name it only to exclude it.
            "_about": bool(re.search(_ABOUT, f"{_clean(r.get('title'))} {results}", re.I)),
            "_drug": any(d in norm(f"{_clean(r.get('title'))} {results}") for d in _DRUGS),
        }

    def _search(sort):
        return get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            {"query": _query, "format": "json", "resultType": "core", "sort": sort, "pageSize": 8},
        )

    try:
        _cited, _recent = _search("CITED desc"), _search("P_PDATE_D desc")
        papers_error = None
    except Exception as _err:
        _cited = _recent = {"resultList": {"result": []}, "hitCount": 0}
        papers_error = str(_err)
    _rows = {}
    for _label, _found in (("plus citées", _cited), ("plus récentes", _recent)):
        for _r in _found["resultList"]["result"]:
            if _r["id"] in _rows:
                _rows[_r["id"]]["sélection"] = "plus citées et plus récentes"
            else:
                _rows[_r["id"]] = _row(_r, _label)
    _all = pd.DataFrame(list(_rows.values()), columns=list(_row({}, "")))
    _all = _all.astype({"_about": bool, "_drug": bool})
    papers = _all[_all["_about"] & _all["_drug"]].drop(columns=["_about", "_drug"]).reset_index(drop=True)
    papers_off_topic = _all[~_all["_about"]].drop(columns=["_about", "_drug"])
    papers_no_drug = _all[_all["_about"] & ~_all["_drug"]].drop(columns=["_about", "_drug"])
    papers_total, papers_query = _cited.get("hitCount", 0), _query
    return papers, papers_error, papers_no_drug, papers_off_topic, papers_query, papers_total


@app.cell
def _(papers, pd, re):
    # The endpoints each publication reports, read from its results as
    # columns: response rate, progression-free and overall survival (medians,
    # hazard ratio, 95 % CI, p). Abstracts give the primary endpoint first, so
    # overall survival, often immature or negative, always gets a value here,
    # even « non rapportée ». In functions: each regex step needs a name.
    _ENDPOINTS = {
        "ORR": r"objective response|overall response|confirmed (?:partial |complete )?response|response rate|\bORR\b",
        "PFS": r"progression-free survival|\bPFS\b",
        "OS": r"overall survival|\bOS\b",
        "other": r"duration of response|disease control|\bDOR\b|\bDCR\b",  # a boundary, not a column
    }
    _N = r"(\d+(?:\.\d+)?)"

    def _stretches(text, name):
        # In each sentence, the words about this endpoint: from the mention
        # (a response rate also from the words before it, "48 (42.9%) had a
        # confirmed response") to the next mention of another endpoint.
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
            marks = sorted((m.start(), m.end(), k) for k, p in _ENDPOINTS.items() for m in re.finditer(p, s))
            for i, (start, _, k) in enumerate(marks):
                if k == name:
                    lo = max([e for b, e, o in marks[:i] if o != name], default=0)
                    if name != "ORR":  # "hazard ratio for OS": a few words before, not the previous figure
                        lo = max(lo, s.find(" ", max(start - 25, 0)) + 1)
                    hi = min([b for b, e, o in marks[i + 1:] if o != name], default=len(s))
                    yield s[lo:hi]

    def _values(text, name):
        out, anchor = [], None  # anchor: where the figure whose 95 % CI follows ends
        medians = sorted({m.end(1): m.group(1) for p in (_N + r"\s*(?:months?|mo)\b", _N + r"\s*(?=(?:vs\.?|versus)\s)") for m in re.finditer(p, text)}.items())
        if name != "ORR" and medians:
            out.append(" vs ".join(v for _, v in medians[:2]) + " mois")
            anchor = medians[0][0]
        elif pct := re.search(_N + r"\s*%(?!\s*(?:CI|confidence))", text):
            out.append(f"{pct.group(1)} %" if name == "ORR" else f"taux {pct.group(1)} %")
            anchor = pct.end()
        if name != "ORR" and re.search(r"(?<!to )(?<![-–])not reached", text):  # not a CI's upper bound
            out.append("médiane non atteinte")
        if name != "ORR" and (hr := re.search(r"(?:hazard ratio|\bHR\b)[^\d]{0,25}?" + _N, text)):
            out.append(f"HR {hr.group(1)}")
            anchor = hr.end()
        if anchor and (ci := re.search(_N + r"\s*(?:-|–|to|,)\s*" + _N, text[anchor : anchor + 45])):
            out.append(f"IC 95 % {ci.group(1)}–{ci.group(2)}")
        if p := re.search(r"\b[pP]\s*([=<>≤])\s*(\d*\.\d+)", text):
            out.append(f"p{p.group(1)}{p.group(2)}")
        if re.search(r"immature|not (?:yet )?mature", text):
            out.append("immature")
        return " ; ".join(out)

    def _endpoint(results, name):
        if not results:
            return "pas de résultats"
        # "·" is the Lancet's decimal point; a follow-up time is not a median survival.
        results = re.sub(r"follow-up[^,;)\]]*", "", results.replace("·", "."))
        stretches = list(_stretches(results, name))
        found = next((v for v in (_values(s, name) for s in stretches) if v), "")
        if found or stretches:
            return found or "mentionnée, sans chiffre"
        return "non rapportée dans le résumé"

    endpoints = pd.DataFrame(
        {_k: [_endpoint(_r, _k) for _r in papers["résultats (résumé)"]] for _k in ("ORR", "PFS", "OS")}, index=papers.index
    )
    return (endpoints,)


@app.cell
def _(av, endpoints, mo, papers, papers_error, papers_no_drug, papers_off_topic, papers_total):
    mo.stop(papers_error is not None, mo.callout(mo.md(f"Europe PMC injoignable : {papers_error}"), kind="warn"))
    mo.vstack([
        mo.md(
            f"**{papers_total} publications d'essais** depuis 2021 ; ci-dessous les 8 plus citées et les 8 plus récentes"
            + (f", moins {len(papers_off_topic)} sur une autre maladie" if len(papers_off_topic) else "")
            + (f" et {len(papers_no_drug)} sans molécule recherchée" if len(papers_no_drug) else "")
            + ". ORR, PFS et OS sont lus dans la section Résultats du résumé, citée en entier."
        ),
        av.table(
            papers.join(endpoints)[
                ["pmid", "titre", "type", "sélection", "année", "ORR", "PFS", "OS", "résultats lus",
                 "revue", "citations", "premier auteur", "résultats (résumé)"]
            ],
            links={"titre": "https://europepmc.org/article/MED/{pmid}"},
            title="Publications d'essais (Europe PMC)",
        ),
    ])
    return


@app.cell
def _(mo):
    mo.md("""
    ## 3. Quel essai a publié quoi
    """)
    return


@app.cell
def _(get_json, pd, re, scope):
    # Trial -> publications: the registry's references (RESULT, given by the
    # sponsor; DERIVED, PubMed records that give the NCT id as their
    # registration), plus Europe PMC articles whose ABSTRACT gives the NCT id.
    # Not the full text: there every review citing the trial matches.
    _pmids = {nct: set(p) for nct, p in zip(scope["nct"], scope["_pmids"])}
    links_error = None
    for _i in range(0, len(_pmids), 40):  # 40 trials per query keeps the URL short
        _batch = list(_pmids)[_i:_i + 40]
        try:
            _hits = get_json(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                {"query": " OR ".join(f'ABSTRACT:"{n}"' for n in _batch), "format": "json", "resultType": "core", "pageSize": 1000},
            )
        except Exception as _err:  # the registry's links are still shown
            links_error = str(_err)
            break
        for _r in _hits["resultList"]["result"]:
            for _nct in set(re.findall(r"NCT\d{8}", _r.get("abstractText") or "")) & set(_batch):
                if _r.get("pmid"):
                    _pmids[_nct].add(_r["pmid"])
    trial_pubs = scope[["nct", "titre", "phase", "statut", "effectif", "motif d'arrêt"]].assign(
        publications=[len(_pmids[n]) for n in scope["nct"]],
        # newest first (PMIDs grow with time), ten at most
        pmid=[", ".join(sorted(_pmids[n], key=int, reverse=True)[:10]) for n in scope["nct"]],
    ).sort_values("publications", ascending=False)
    unpublished = trial_pubs[trial_pubs["publications"] == 0]
    return links_error, trial_pubs, unpublished


@app.cell
def _(av, links_error, mo, trial_pubs, unpublished):
    mo.vstack([
        *([mo.callout(mo.md(f"Europe PMC injoignable, liens du registre seulement : {links_error}"), kind="warn")] if links_error else []),
        mo.md(
            f"**{len(trial_pubs) - len(unpublished)} essais** ont au moins une publication liée (registre ou NCT cité dans le résumé) ; "
            f"**{len(unpublished)} n'ont encore aucun résultat publié** retrouvé."
        ),
        av.table(
            trial_pubs,
            links={"nct": "https://clinicaltrials.gov/study/{nct}"},
            title="Essais et publications liées (PMID, plus récent d'abord)",
        ),
    ])
    return


@app.cell
def _(
    SCOPE_TEXT,
    drug_counts,
    endpoints,
    excluded,
    mo,
    on_drug,
    papers,
    papers_no_drug,
    papers_off_topic,
    papers_query,
    papers_total,
    phase_counts,
    scope,
    status_counts,
    tested,
    trial_pubs,
    trials_error,
    unpublished,
):
    # What the answer rests on, computed from the data above and printed so
    # that `python notebook.py` shows it to the agent.
    # Trial counts: all over `scope`, every phase-3 trial listed (none dropped).
    # Phase 3 and phase 2/3 together, the header says how many of each; trials
    # of none of the searched drugs come last and are counted in the header.
    _phase3 = scope.assign(molécules=tested)[scope["phase"].str.contains("Phase 3")]
    _phase3 = _phase3.sort_values("molécules", key=lambda m: m.map(len) == 0, kind="stable").to_dict("records")
    _p23 = sum(t["phase"] == "Phase 2/Phase 3" for t in _phase3)
    _other = sum(not t["molécules"] for t in _phase3)
    _withdrawn = int((excluded["statut"] == "WITHDRAWN").sum())
    facts = [f"ClinicalTrials.gov injoignable : {trials_error}"] if trials_error else []
    facts += [
        f"Périmètre de tous les comptes d'essais : {len(scope)} {SCOPE_TEXT} "
        f"(écartés : {_withdrawn} retirés, {len(excluded) - _withdrawn} études observationnelles ou d'accès élargi)",
        "Par phase : " + ", ".join(f"{k} {v}" for k, v in phase_counts.items()),
        "Par statut : " + ", ".join(f"{k} {v}" for k, v in status_counts.items()),
        f"Essais recrutant (statut RECRUITING) : {status_counts.get('RECRUITING', 0)}",
        f"Essais testant une molécule recherchée dans un bras expérimental : {int(on_drug.sum())}",
        "Molécules les plus testées (bras expérimentaux seulement, synonymes fusionnés) : "
        + ", ".join(f"{r.traitement} ({r.essais})" for r in drug_counts.itertuples() if r.essais),
        f"Essais de phase 3 ou 2/3 ({len(_phase3)} = {len(_phase3) - _p23} phase 3 + {_p23} phase 2/3 ; "
        f"dont {_other} sans molécule recherchée, listés en dernier) : " + ("; ".join(
            f"{t['nct']} {t['titre']} [{t['statut']} ; {t['effectif']} ; molécule : {', '.join(t['molécules']) or 'aucune des recherchées'}"
            + (" ; arrêt : " + t["motif d'arrêt"] if t["motif d'arrêt"] else "") + "]"
            for t in _phase3
        ) or "aucun"),
    ]
    # Publications (literature search): the query, what was set aside, and for
    # each paper its type, the endpoints read and its results section, whole.
    facts += [
        f"Recherche Europe PMC : {papers_query} ; {papers_total} publications, les 8 plus citées et les 8 plus récentes lues",
        "Écartées, sur une autre maladie : "
        + ("; ".join(f"PMID {r.pmid} {r.titre}" for r in papers_off_topic.itertuples()) or "aucune"),
        "Écartées, sans molécule recherchée : "
        + ("; ".join(f"PMID {r.pmid} {r.titre}" for r in papers_no_drug.itertuples()) or "aucune"),
    ]
    for _p in papers.join(endpoints).to_dict("records"):
        facts.append(
            f"Publication PMID {_p['pmid']} ({_p['premier auteur']} et al., {_p['revue']}, {_p['année']}, "
            f"{_p['citations']} citations ; {_p['type']} ; {_p['sélection']}) : {_p['titre']} — "
            f"ORR : {_p['ORR']} — PFS : {_p['PFS']} — OS : {_p['OS']} — "
            f"résultats ({_p['résultats lus']}) : {_p['résultats (résumé)'] or '—'}"
        )
    # Trial <-> publication links (section 3)
    _trial_of = {pmid: t["nct"] for t in trial_pubs.to_dict("records") for pmid in t["pmid"].split(", ") if pmid}
    facts += [
        "Publications par essai : " + ("; ".join(f"{t['nct']} ({t['titre'][:60]}) : PMID {t['pmid']}" for t in trial_pubs[trial_pubs["publications"] > 0].to_dict("records")) or "aucune"),
        f"Essais sans résultat publié retrouvé ({len(unpublished)}) : " + (", ".join(f"{t['nct']} [{t['phase']}, {t['statut']}]" for t in unpublished.to_dict("records")) or "aucun"),
        "Publications ci-dessus rattachées à leur essai : " + (", ".join(f"PMID {p} → {_trial_of[p]}" for p in papers["pmid"] if p in _trial_of) or "aucune"),
    ]
    print("\n".join(facts))
    mo.md("## Résumé des données\n\n" + "\n".join(f"- {f}" for f in facts))
    return


@app.cell
def _(mo):
    mo.md("""
    ## Sources

    ClinicalTrials.gov API v2 · Europe PMC REST API.
    """)
    return


@app.cell
def _(SAVE_RAW, av, calls, mo, papers, pd, re, requests, trial_pubs, trials):
    # « Provenance »: which release of each source answered, the exact request,
    # when. The data cells' outputs (trials, papers, trial_pubs) are arguments
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
