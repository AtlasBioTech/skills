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
def _(drug_counts, mo, on_drug, papers, phase_counts, status_counts, trials, trials_total):
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
    for _p in papers.head(5).to_dict("records"):
        facts.append(
            f"Publication PMID {_p['pmid']} ({_p['premier auteur']} et al., {_p['revue']}, {_p['année']}, "
            f"{_p['citations']} citations) : {_p['titre']} — résultats : {_p['résultats (résumé)']}"
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
