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

    # The question, as registry search terms (English: both registries index in English).
    CONDITION = "ovarian cancer"
    INTERVENTION = "PARP inhibitor OR olaparib OR niraparib OR rucaparib OR talazoparib OR senaparib"
    SINCE = "2021-01-01"  # "récents": trials started in the last five years
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


@app.cell
def _(SAVE_RAW, av, calls, mo, papers, pd, re, requests, trials):
    # « Provenance »: which release of each source answered, the exact request,
    # when. The data cells' outputs (trials, papers) are arguments
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
