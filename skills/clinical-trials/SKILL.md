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
   results from Europe PMC, each in a cell that calls the API with `requests`.
   Your own web-fetch and shell tools are only for trying a query before you
   write that cell.
2. **Show three tables** with `av.table`: the trials (NCT id linked to the
   trial page), the trial publications (title linked to the article), and
   one row per trial with its publications (PMIDs), so the trials without
   published results show.
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
| Drug codes | `GET https://www.ebi.ac.uk/chembl/api/data/molecule.json?pref_name__in=SOTORASIB,ADAGRASIB,…&only=pref_name,molecule_synonyms` (one call for all drugs) → `molecules[].molecule_synonyms[].molecule_synonym`; keep only code-shaped names (`AMG-510`, `JDQ443`): the lists also hold other drugs' names |
| Trials | `GET https://clinicaltrials.gov/api/v2/studies` with `query.cond` (disease **and its abbreviation**, e.g. `non-small cell lung cancer OR NSCLC`: basket trials register "solid tumours" and name the disease only in keywords), `query.intr` (drugs and their codes, `OR`-separated; add the target, e.g. `KRAS G12C inhibitor`), `filter.advanced=AREA[CompletionDate]RANGE[2021-01-01,MAX] OR AREA[CompletionDate]MISSING` for "recent" (running at some point since then), `fields=NCTId,Acronym,BriefTitle,StudyType,OverallStatus,WhyStopped,Phase,StartDate,CompletionDate,LeadSponsorName,EnrollmentInfo,HasResults,ArmsInterventionsModule,ReferencesModule`, `pageSize=200`, `countTotal=true`, then `pageToken=nextPageToken` until there is none → `studies[].protocolSection`, `totalCount` |
| Trial publications | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=…&format=json&resultType=core&sort=CITED desc` with `PUB_TYPE:"Clinical Trial"` (or `"Randomized Controlled Trial"`, `"Clinical Trial, Phase III"`) and `FIRST_PDATE:[2021-01-01 TO 3000-01-01]`; `TITLE:`/`ABSTRACT:` narrow the terms → `resultList.result[]`: `pmid`, `title`, `journalInfo.journal.title`, `pubYear`, `citedByCount`, `authorString`, `abstractText` |
| Trial ↔ publication | the trial's `referencesModule.references[]` of `type` `RESULT` or `DERIVED` (`pmid`), plus Europe PMC `ABSTRACT:"NCT04685135" OR ABSTRACT:"…"` (40 ids per call, `resultType=core`), each hit assigned by the NCT ids in its `abstractText`. Not a bare `"NCT…"` query: it searches full texts, where every review citing the trial matches |
| A trial's page | `https://clinicaltrials.gov/study/{nct}` · an article: `https://europepmc.org/article/MED/{pmid}` |

Drug names you put in `query.intr` are search terms, not facts: list the
class and the names you know (approved and investigational), and let the
registry say which trials test them. Count a drug only where an `EXPERIMENTAL`
arm gives it (`armGroups[].type`; `interventions[].armGroupLabels`), under any
of its names (`interventions[].otherNames`, ChEMBL codes): a comparator arm
(sotorasib in Krascendo 1) does not test it, and `MRTX849` is adagrasib.

## Recipe

Read [`references/notebook.py`](references/notebook.py): a complete notebook
(PARP inhibitors in ovarian cancer) that runs as is. For another question,
copy its cells and change `CONDITION`, `INTERVENTION`, `SINCE` and
`PAPERS_QUERY`; keep the structure: question → drug codes (ChEMBL) → trials
(ClinicalTrials.gov) table → drugs counted from the trials → trial
publications (Europe PMC) table → which trial published what (table) →
**facts** → sources.

Every trial count comes from **one set, named in the text**: interventional
trials, not withdrawn, running at some point since `SINCE`
(`scope`). Withdrawn trials (they never enrolled anyone) and observational
or expanded-access studies are listed apart, never added to the totals.

The facts cell computes, from the data above, what the answer rests on, and
also `print`s it, so `python notebooks/<name>.py` shows it to you: that set
and its size, by phase and status; the trials recruiting; the drugs most
tested in experimental arms; **every** phase-3 trial with its status,
enrolment (actual or planned) and why it stopped; the most cited trial
publications with the results section of their abstract; the publications
of each trial and the trials with no published result.

## Answer from the data

Your chat answer states these facts with their numbers and sources (NCT ids,
PMIDs), in French, as the notebook found them. Efficacy figures (response
rate, progression-free survival, hazard ratio) only from an abstract the
notebook printed, with its PMID; if a figure is not there, say it was not
checked rather than quoting it from memory. Say which trials are still
recruiting, which have **no published results yet**, and, for a stopped or
truncated trial, the registry's reason and actual enrolment. Every number you
give about the trials is a count over the set the notebook states; say that
set once (« sur N essais interventionnels… »).

## Before you end your turn

1. Re-read the notebook: it contains three `av.table(` calls, each the last
   expression of its cell, and `requests.get` calls to
   `clinicaltrials.gov/api/v2` and Europe PMC.
2. Run `marimo check notebooks/<name>.py` then `python notebooks/<name>.py`
   (must exit 0) from the project folder. Fix and re-run until both pass.
3. Answer in the chat from the facts it printed, and point to the tables.
