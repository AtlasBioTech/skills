---
name: scientific-rigor
description: How to word a scientific answer so a clinician can trust it - precise, sourced definitions (gene vs protein, HGNC and UniProt identifiers, domains with residue ranges, UniProt function), statements marked as Observé (the notebook's data), Rapporté (a cited paper, with its experimental level and what was read) or Hypothèse, no causal claim a source does not make, error bars and p-values that say what they are (SD, SEM or CI, what n counts, multiple-comparison correction), and a conclusion followed by the next step that would test it. Use for any answer about a gene, a protein, a variant, a mechanism, a pathway, a drug, what the literature says, or any quantitative result (a comparison, a mean, a figure with error bars, a p-value).
---

# Scientific rigor in an answer

The reader is a clinician or a biologist who will act on what you write.
Five faults make an answer untrustworthy: a vague definition, a conclusion
drawn from a paper's title, a causal story no source tells, a number whose
uncertainty is hidden or mislabelled, and a conclusion handed over as if
nothing could overturn it. This skill is how to avoid them. Load `atlas-viewers` (or `clinical-trials`) for how to
fetch the data; this one is about what you then write.

## 1. Definitions: precise and sourced

- Name the **gene** and the **protein** separately: the *TP53* gene
  (HGNC:11998) codes the p53 protein (UniProt P04637, 393 amino acids).
- **Domains with their residue ranges**, from UniProt's features: « domaine
  de liaison à l'ADN (résidus 102–292) », not « le domaine central ».
- **Function from UniProt's Function comment**, paraphrased and attributed:
  « facteur de transcription qui induit l'arrêt du cycle cellulaire, la
  réparation de l'ADN ou l'apoptose (UniProt) ».
- Each fact with its source. The notebook already fetches all of this
  (UniProt entry, cross-references, features): use its output, not memory.

## 2. Three kinds of statements

Mark each claim with what it rests on, inline, with a short bold prefix:

- **Observé** — what this notebook's data shows (UniProt, ClinVar,
  AlphaFold, counts computed in a cell).
- **Rapporté** — what a cited paper reports: first author, journal, year,
  PMID; the **experimental level** (in vitro, lignée cellulaire, souris,
  cohorte humaine, essai clinique); and **what you read** (résumé, texte
  intégral). Quote or closely paraphrase the sentence that supports it.
- **Hypothèse** — your inference, or a mechanism no cited source states at
  this level. Say it is one.

For a long answer, group them under headings (Observé / Rapporté /
Hypothèse) instead of prefixing each line.

## 3. Literature: read before you conclude

- **Never conclude from a title.** Use the abstract, or the full text when
  the paper is open access. The notebook's « lu » column says which; a
  paper read only by its title is listed, not cited for a claim.
- Say what was read: « d'après le résumé », « texte intégral, résultats ».

## 4. No causal claim without a source at that level

- A causal link (« X entraîne Y ») only when a cited source makes it, and
  only at the level it was shown: a mouse result is stated as a mouse
  result, a cell-line result as a cell-line result, a correlation in a
  cohort as a correlation.
- A structural difference is not a mechanism: « la structure est
  différente, donc plus de métastases » is two claims and a « donc » no
  source supports.

## 5. Every reference verified by an API call

Never write a citation from memory, even a famous one: authors, year and
PMID are exactly what a model gets wrong. Check it in the notebook (a cell)
or once in a script before you write it:

```python
import requests
r = requests.get(
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
    params={"query": "EXT_ID:15607981 AND SRC:MED", "format": "json", "resultType": "core"},
    timeout=30,
).json()["resultList"]["result"][0]
print(r["authorString"], r["journalInfo"]["journal"]["isoabbreviation"], r["pubYear"], r["title"])
print(r["abstractText"])  # the sentence you cite must be in here (or in the full text)
```

If the paper is not found, or the abstract does not say what you meant to
cite it for, do not cite it.

## 6. Numbers: say what the bars, n and p-values are

For a quantitative result (a comparison between groups, a mean, a
difference, a correlation), show its uncertainty, and say exactly what it is.
Counts and lookups (the number of ClinVar variants, a residue range) need
none of this.

- **Show the uncertainty**: error bars on the figure, an interval in the
  text (« 2,4 fois (IC 95 % 1,6–3,5) »), rather than a bare mean.
- **Name the bars** in the figure's caption and in the chat: écart-type
  (ET, the spread of the data), erreur standard de la moyenne (ESM, the
  precision of the mean) or intervalle de confiance à 95 % (IC 95 %).
  Prefer ET or IC 95 %: ESM bars look tighter than the data are, so never
  draw them unlabelled.
- **Say what n counts**: the independent unit (patient, donor, animal,
  independent experiment), not cells, wells or technical replicates.
  3 donors × 5 000 cells is n = 3: average each donor's cells, then compare
  the donors. Treating each cell as a replicate makes any difference
  « significant ».
- **Tests only when a claim needs one.** Don't put a p-value on every
  figure: an exploratory plot is fine with its bars. When you do test (the
  scientist asked, or the answer claims a difference), name the test and
  give the reason in one line (« test t de Welch : deux groupes, variances
  inégales » ; « Mann-Whitney : n = 4 par groupe, pas d'hypothèse de
  normalité »).
- **Say whether you corrected for multiple comparisons**, and how many you
  ran: « 20 gènes testés, correction de Benjamini-Hochberg » ; for one
  comparison, « une seule comparaison, pas de correction ».
- **If a test cannot be done honestly** (n = 1 per group, the unit is
  unclear, assumptions clearly broken), say so and show the data instead
  of forcing a p-value.

A caption that says it all, in one line:

> Moyenne ± ET, n = 3 donneurs par condition (chaque point est un donneur,
> moyenne de ses cellules). Test t de Welch, une seule comparaison :
> p = 0,04.

## 7. After a conclusion: the next step that would test it

When the answer draws a conclusion (« X augmente Y », « le cluster 3 est
une population distincte »), end with the next step that would confirm it,
if something material could overturn it: a small n, a batch confounded with
the condition, a single study, a mouse-only result.

- **Phrase it as a next step**, in one or two lines, not as a list of
  limitations: « Pour le confirmer : comparer l'effet au sein de chaque
  lot, les deux conditions ayant été préparées dans des lots différents. »
- **Only what could change the conclusion.** Nothing to say is fine: say
  nothing. No generic « limites » section, no checklist.
- **Not for every turn.** Fetching data, drawing a figure or exploring
  draws no conclusion, so it needs no next step.
- The full picture (data, method, confounders, what cannot be concluded)
  only when the scientist asks for it.

## Worked example: TP53 p.R175H

Vague, unsourced, causal shortcut:

> p53 est le gardien du génome. R175H change la structure de la protéine,
> donc elle favorise les métastases (Smith et al., 2015).

Rigorous:

> Le gène *TP53* (HGNC:11998) code la protéine p53 (UniProt P04637, 393
> acides aminés), un facteur de transcription qui induit l'arrêt du cycle
> cellulaire, la réparation de l'ADN ou l'apoptose (UniProt, Function).
>
> - **Observé** — R175 est dans le domaine de liaison à l'ADN (résidus
>   102–292, UniProt), à côté de C176, l'un des quatre résidus qui lient
>   l'ion zinc (C176, H179, C238, C242). ClinVar classe p.R175H pathogène.
> - **Rapporté** — chez la **souris**, les tumeurs des animaux porteurs de
>   la mutation équivalente (R172H) métastasent fréquemment (Lang et al.,
>   *Cell* 2004, PMID 15607981, résumé lu) ; Olive et al. (*Cell* 2004,
>   PMID 15607980, résumé lu) décrivent chez ces souris un spectre tumoral
>   différent de la simple perte de p53.
> - **Hypothèse** — la proximité du site de liaison du zinc suggère que
>   R175H perturbe le repliement du domaine ; ce notebook ne le teste pas,
>   et ces études ne montrent pas que ce mécanisme explique les métastases
>   chez l'humain.

Each reference above was checked with the call in section 5, and each
« Rapporté » sentence paraphrases its abstract.
