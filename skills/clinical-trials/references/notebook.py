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
    SINCE = "2021-01-01"  # "récents": trials started in the last five years
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
def _(CONDITION, INTERVENTION, SINCE, get_json, pd):
    # ClinicalTrials.gov API v2: one row per trial, only the fields shown.
    _fields = ",".join([
        "NCTId", "BriefTitle", "OverallStatus", "Phase", "StartDate",
        "LeadSponsorName", "EnrollmentCount", "InterventionName", "HasResults",
    ])
    _params = {
        "query.cond": CONDITION,
        "query.intr": INTERVENTION,
        "filter.advanced": f"AREA[StartDate]RANGE[{SINCE},MAX]",
        "fields": _fields,
        "sort": "StartDate:desc",
        "pageSize": 200,
        "countTotal": "true",
    }
    try:
        _page = get_json("https://clinicaltrials.gov/api/v2/studies", _params)
        trials_error = None
    except Exception as _err:  # a failed request is shown, the notebook keeps running
        _page, trials_error = {"studies": [], "totalCount": 0}, str(_err)

    def _row(study):
        p = study["protocolSection"]
        design = p.get("designModule", {})
        return {
            "nct": p["identificationModule"]["nctId"],
            "titre": p["identificationModule"].get("briefTitle", ""),
            # ["PHASE1", "PHASE2"] -> "Phase 1/Phase 2"; "NA" (not applicable: observational, device) -> "n/a"
            "phase": "/".join(ph.replace("EARLY_PHASE", "Phase précoce ").replace("PHASE", "Phase ") for ph in design.get("phases", []) if ph != "NA") or "n/a",
            "statut": p.get("statusModule", {}).get("overallStatus", ""),
            "début": p.get("statusModule", {}).get("startDateStruct", {}).get("date", ""),
            "promoteur": p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", ""),
            "effectif": design.get("enrollmentInfo", {}).get("count"),
            "traitements": ", ".join(i["name"] for i in p.get("armsInterventionsModule", {}).get("interventions", [])),
            "résultats": "oui" if study.get("hasResults") else "non",
        }

    trials = pd.DataFrame([_row(s) for s in _page["studies"]])
    trials_total = _page.get("totalCount", len(trials))
    return trials, trials_error, trials_total


@app.cell
def _(av, mo, trials, trials_error, trials_total):
    mo.stop(trials_error is not None, mo.callout(mo.md(f"ClinicalTrials.gov injoignable : {trials_error}"), kind="danger"))
    mo.vstack([
        mo.md(f"**{trials_total} essais** ont commencé depuis 2021 (les {len(trials)} plus récents ci-dessous ; cliquez un identifiant pour la fiche de l'essai)."),
        av.table(
            trials,
            links={"nct": "https://clinicaltrials.gov/study/{nct}"},
            title="Essais cliniques (ClinicalTrials.gov)",
        ),
    ])
    return


@app.cell
def _(INTERVENTION, pd, re, trials):
    # Which of the searched drugs the trials test, counted from the registry,
    # not from memory. The drug names are the search terms themselves.
    _drugs = [d.strip() for d in INTERVENTION.split(" OR ") if " " not in d.strip()]
    _tests = lambda d: trials["traitements"].str.contains(rf"\b{re.escape(d)}\b", case=False) if len(trials) else pd.Series(dtype=bool)
    drug_counts = pd.DataFrame(
        [{"traitement": d, "essais": int(_tests(d).sum())} for d in _drugs], columns=["traitement", "essais"]
    ).sort_values("essais", ascending=False)
    # A registry search also matches trials that only mention the drugs (e.g.
    # "after a PARP inhibitor"): the phase-3 list keeps those that give one.
    on_drug = pd.concat([_tests(d) for d in _drugs], axis=1).any(axis=1) if len(trials) else pd.Series(dtype=bool)
    phase_counts = trials["phase"].value_counts() if len(trials) else pd.Series(dtype=int)
    status_counts = trials["statut"].value_counts() if len(trials) else pd.Series(dtype=int)
    return drug_counts, on_drug, phase_counts, status_counts


@app.cell
def _(mo):
    mo.md("""
    ## 2. Les résultats publiés (Europe PMC)
    """)
    return


@app.cell
def _(PAPERS_QUERY, SINCE, get_json, pd, re):
    # Trial publications: the most cited AND the most recent (citation counts
    # alone keep only the older trials), each with how it was selected, its
    # type, and the results section of its abstract, whole.
    from html import unescape as _unescape

    # The disease as titles and results write it (change it with CONDITION):
    # a paper about another disease is set aside, even when its background or
    # methods name this one ("excluding NSCLC").
    _ABOUT = r"ovar"
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
    papers = _all[_all["_about"]].drop(columns="_about").reset_index(drop=True)
    papers_off_topic = _all[~_all["_about"]].drop(columns="_about")
    papers_total, papers_query = _cited.get("hitCount", 0), _query
    return papers, papers_error, papers_off_topic, papers_query, papers_total


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
def _(av, endpoints, mo, papers, papers_error, papers_off_topic, papers_total):
    mo.stop(papers_error is not None, mo.callout(mo.md(f"Europe PMC injoignable : {papers_error}"), kind="warn"))
    mo.vstack([
        mo.md(
            f"**{papers_total} publications d'essais** depuis 2021 ; ci-dessous les 8 plus citées et les 8 plus récentes"
            + (f", moins {len(papers_off_topic)} sur une autre maladie" if len(papers_off_topic) else "")
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
def _(drug_counts, endpoints, mo, on_drug, papers, papers_off_topic, papers_query, papers_total, phase_counts, status_counts, trials, trials_total):
    # What the answer rests on, computed from the data above and printed so
    # that `python notebook.py` shows it to the agent.
    _phase3 = trials[trials["phase"].str.contains("Phase 3") & on_drug] if len(trials) else trials
    facts = [
        f"Essais enregistrés depuis 2021 : {trials_total}",
        "Par phase : " + ", ".join(f"{k} {v}" for k, v in phase_counts.items()),
        "Par statut : " + ", ".join(f"{k} {v}" for k, v in status_counts.items()),
        "Traitements les plus testés : " + ", ".join(f"{r.traitement} ({r.essais})" for r in drug_counts.itertuples() if r.essais),
        "Essais de phase 3 : " + ("; ".join(f"{r.nct} {r.titre} [{r.statut}]" for r in _phase3.head(8).itertuples()) or "aucun"),
    ]
    # Publications (literature search): the query, what was set aside, and for
    # each paper its type, the endpoints read and its results section, whole.
    facts += [
        f"Recherche Europe PMC : {papers_query} ; {papers_total} publications, les 8 plus citées et les 8 plus récentes lues",
        "Écartées, sur une autre maladie : "
        + ("; ".join(f"PMID {r.pmid} {r.titre}" for r in papers_off_topic.itertuples()) or "aucune"),
    ]
    for _p in papers.join(endpoints).to_dict("records"):
        facts.append(
            f"Publication PMID {_p['pmid']} ({_p['premier auteur']} et al., {_p['revue']}, {_p['année']}, "
            f"{_p['citations']} citations ; {_p['type']} ; {_p['sélection']}) : {_p['titre']} — "
            f"ORR : {_p['ORR']} — PFS : {_p['PFS']} — OS : {_p['OS']} — "
            f"résultats ({_p['résultats lus']}) : {_p['résultats (résumé)'] or '—'}"
        )
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
