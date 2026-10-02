---
name: clinical-trials
description: Find and summarise clinical trials of a drug, a drug class or a target in a disease, in a marimo notebook that queries ClinicalTrials.gov (API v2) and Europe PMC and shows the trials and their publications with av.table. Use for any question about clinical trials, essais cliniques, trial results, treatments being tested, or recent studies of a therapy (e.g. "essais sur les inhibiteurs de KRAS G12C dans le cancer du poumon").
---

# Clinical trials in a marimo notebook

The scientist reads the notebook, not your tool calls. A question about
clinical trials is answered only when **the notebook itself queries the trial
registry and the literature and shows them in tables**. A table of trials or
response rates that you typed from memory, or copied from a web page you
fetched, is not an answer, even if it is correct: trial names, NCT numbers,
drug codes and percentages are exactly what a model gets wrong.

## Rules

1. **Query in the notebook.** Trials come from ClinicalTrials.gov, published
   results from Europe PMC, each in a cell that calls the API through the
   reference's `get_json` helper (`requests` inside), which logs each request
   for the « Provenance » table and saves the raw response. Your own
   web-fetch and shell tools are only for trying a query before you write
   that cell.
2. **Show both tables** with `av.table`: the trials (NCT id linked to the
   trial page) and the trial publications (title linked to the article).
3. `import atlas_viewers as av` in the first cell, next to `import marimo as mo`.
4. A table is displayed only as the **last expression of its cell** (alone,
   or inside `mo.vstack([...])`).
5. **Wrap every network call in `try/except`** and show the failure with
   `mo.callout(..., kind="warn")`: the notebook must still run top to bottom.
6. Search in **English** (both registries index in English); write the
   notebook's text and your answer in French.

## Where the data comes from

| What | Call |
|---|---|
| Trials | `GET https://clinicaltrials.gov/api/v2/studies` with `query.cond` (disease), `query.intr` (drugs, `OR`-separated; add the target, e.g. `KRAS G12C inhibitor`), optionally `query.term` (biomarker, e.g. `KRAS G12C`), `filter.advanced=AREA[StartDate]RANGE[2021-01-01,MAX]` for "recent", `fields=NCTId,BriefTitle,OverallStatus,Phase,StartDate,LeadSponsorName,EnrollmentCount,InterventionName,HasResults`, `sort=StartDate:desc`, `pageSize=200`, `countTotal=true` → `studies[].protocolSection`, `totalCount` |
| Trial publications | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=…&format=json&resultType=core&sort=CITED desc` with `PUB_TYPE:"Clinical Trial"` (or `"Randomized Controlled Trial"`, `"Clinical Trial, Phase III"`) and `FIRST_PDATE:[2021-01-01 TO 3000-01-01]`; `TITLE:`/`ABSTRACT:` narrow the terms → `resultList.result[]`: `pmid`, `title`, `journalInfo.journal.title`, `pubYear`, `citedByCount`, `authorString`, `abstractText` |
| A trial's page | `https://clinicaltrials.gov/study/{nct}` · an article: `https://europepmc.org/article/MED/{pmid}` |

Drug names you put in `query.intr` are search terms, not facts: list the
class and the names you know (approved and investigational), and let the
registry say which trials test them.

## Recipe

Read [`references/notebook.py`](references/notebook.py): a complete notebook
(PARP inhibitors in ovarian cancer) that runs as is. For another question,
copy its cells and change `CONDITION`, `INTERVENTION`, `SINCE` and
`PAPERS_QUERY`; keep the structure: question → trials (ClinicalTrials.gov)
table → drugs counted from the trials → trial publications (Europe PMC)
table → **facts** → sources → **provenance**.

The facts cell computes, from the data above, what the answer rests on, and
also `print`s it, so `python notebooks/<name>.py` shows it to you: the number
of trials, by phase and status; the drugs most tested; the phase-3 trials;
the most cited trial publications with the results section of their
abstract.

The last cell, « Provenance », lists every request: source, release
(ClinicalTrials.gov API version and data date; Europe PMC publishes none and
the table says so), exact query and UTC date, and prints one line per
source. The raw responses are saved, gzipped, under `provenance/<date>/`
next to the notebook, with `requests.json`, the full log.

## Answer from the data

Your chat answer states these facts with their numbers and sources (NCT ids,
PMIDs), in French, as the notebook found them. Efficacy figures (response
rate, progression-free survival, hazard ratio) only from an abstract the
notebook printed, with its PMID; if a figure is not there, say it was not
checked rather than quoting it from memory. Say which trials are still
recruiting. Say when the registry was queried and its data date, as the
« Provenance » line printed it (« ClinicalTrials.gov, données du … »).

## Before you end your turn

1. Re-read the notebook: it contains two `av.table(` calls, each the last
   expression of its cell, `requests.get` calls to
   `clinicaltrials.gov/api/v2` and Europe PMC, and the « Provenance » cell
   last.
2. Run `marimo check notebooks/<name>.py` then `python notebooks/<name>.py`
   (must exit 0) from the project folder. Fix and re-run until both pass.
3. Answer in the chat from the facts it printed, and point to the tables.
