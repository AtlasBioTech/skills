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
def _(requests):
    # One helper for every public API: a timeout, and an error that says which URL failed.
    def get_json(url, params=None):
        response = requests.get(url, params=params, timeout=60, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()

    # The question, as registry search terms (English: both registries index in English).
    CONDITION = "ovarian cancer"
    INTERVENTION = "PARP inhibitor OR olaparib OR niraparib OR rucaparib OR talazoparib OR senaparib"
    SINCE = "2021-01-01"  # "récents": trials running at some point since then, publications since then
    # For the literature: the drugs or the target in the title or abstract, the disease in the title.
    PAPERS_QUERY = (
        '(ABSTRACT:"PARP inhibitor" OR TITLE:olaparib OR TITLE:niraparib OR TITLE:rucaparib) '
        'AND (TITLE:ovarian OR TITLE:ovary)'
    )
    return CONDITION, INTERVENTION, PAPERS_QUERY, SINCE, get_json


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
def _(PAPERS_QUERY, SINCE, get_json, pd, re):
    # Trial publications only, most cited first; the abstract's results section
    # is kept so the answer quotes numbers from the articles, not from memory.
    _query = (
        f"{PAPERS_QUERY} AND (PUB_TYPE:\"Clinical Trial\" OR PUB_TYPE:\"Randomized Controlled Trial\" "
        f"OR PUB_TYPE:\"Clinical Trial, Phase III\" OR PUB_TYPE:\"Clinical Trial, Phase II\") "
        f"AND FIRST_PDATE:[{SINCE} TO 3000-01-01]"
    )

    def _results(abstract):
        # The results section of a structured abstract ("Results", or
        # "Findings" in the Lancet journals), else the whole abstract.
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", abstract or "")).strip()
        section = re.search(r"\b(?:Results?|Findings)\b:?\s+(.*?)(?:\b(?:Conclusions?|Interpretation)\b|$)", text)
        return (section.group(1) if section else text)[:400]

    try:
        _hits = get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            {"query": _query, "format": "json", "resultType": "core", "sort": "CITED desc", "pageSize": 25},
        )
        papers_error = None
    except Exception as _err:
        _hits, papers_error = {"resultList": {"result": []}, "hitCount": 0}, str(_err)
    papers = pd.DataFrame(
        [
            {
                "pmid": r.get("pmid", ""),
                "titre": re.sub(r"<[^>]+>", "", r.get("title", "")),
                "revue": r.get("journalInfo", {}).get("journal", {}).get("title", ""),
                "année": r.get("pubYear", ""),
                "citations": r.get("citedByCount", 0),
                "premier auteur": (r.get("authorString") or "").split(",")[0],
                "résultats (résumé)": _results(r.get("abstractText")),
            }
            for r in _hits["resultList"]["result"]
        ]
    )
    papers_total = _hits.get("hitCount", 0)
    return papers, papers_error, papers_total


@app.cell
def _(av, mo, papers, papers_error, papers_total):
    mo.stop(papers_error is not None, mo.callout(mo.md(f"Europe PMC injoignable : {papers_error}"), kind="warn"))
    mo.vstack([
        mo.md(f"**{papers_total} publications d'essais** depuis 2021 ; les plus citées :"),
        av.table(
            papers,
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
    excluded,
    mo,
    on_drug,
    papers,
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
    for _p in papers.head(5).to_dict("records"):
        facts.append(
            f"Publication PMID {_p['pmid']} ({_p['premier auteur']} et al., {_p['revue']}, {_p['année']}, "
            f"{_p['citations']} citations) : {_p['titre']} — résultats : {_p['résultats (résumé)']}"
        )
    # Trial <-> publication links (section 3)
    _trial_of = {pmid: t["nct"] for t in trial_pubs.to_dict("records") for pmid in t["pmid"].split(", ") if pmid}
    facts += [
        "Publications par essai : " + ("; ".join(f"{t['nct']} ({t['titre'][:60]}) : PMID {t['pmid']}" for t in trial_pubs[trial_pubs["publications"] > 0].to_dict("records")) or "aucune"),
        f"Essais sans résultat publié retrouvé ({len(unpublished)}) : " + (", ".join(f"{t['nct']} [{t['phase']}, {t['statut']}]" for t in unpublished.to_dict("records")) or "aucun"),
        "Publications ci-dessus rattachées à leur essai : " + (", ".join(f"PMID {p} → {_trial_of[p]}" for p in papers.head(5).get("pmid", []) if p in _trial_of) or "aucune"),
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


if __name__ == "__main__":
    app.run()
