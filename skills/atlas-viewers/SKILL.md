---
name: atlas-viewers
description: Show a protein, a 3D structure, variants or a result table in a marimo notebook with the Atlas viewers (atlas_viewers - av.structure, av.variants, av.table). Use for any question about a gene, a protein, a mutation or variant (p.R175H, G12D, c.524G>A), an AlphaFold or PDB structure, ClinVar classifications, or a table of results to show in the notebook.
---

# Atlas viewers in a marimo notebook

The scientist reads the notebook, not your tool calls. A question about a
protein or a variant is answered only when **the notebook itself fetches the
data and shows it with the viewers**. A notebook made of `mo.md` text that you
typed from what you read on the web is not an answer, even if it is correct.

## Rules

1. **Fetch in the notebook.** Every number you report (length, domains,
   ClinVar classification, article count) comes from a cell that calls the
   public API with `requests`. Your own web-fetch tool is only for exploring
   an API before you write that cell.
2. **Show all three viewers** for a protein or variant question:
   - `av.structure` — the AlphaFold model, the variant's residue highlighted;
   - `av.variants` — the ClinVar variants along the protein, UniProt domains drawn;
   - `av.table` — the ClinVar rows (or articles), with links.
3. `import atlas_viewers as av` in the first cell, next to `import marimo as mo`,
   and return `av` from it.
4. **Write the residue number literally** in the viewer call, so a reader
   sees which residue is shown: `highlight=[12], labels={12: "G12D"}`.
5. A viewer is displayed only as the **last expression of its cell** (alone,
   or inside `mo.vstack([...])`). Not `print(...)`, not assigned and dropped.
6. **Wrap every network call in `try/except`** and show the failure with
   `mo.callout(..., kind="warn")`: the notebook must still run top to bottom.

## API

```python
import atlas_viewers as av

av.structure(source, highlight=[12], labels={12: "G12D"}, color_by="plddt",
             title="", subtitle="", height=480)
# source: URL (downloaded by the kernel), local path or bytes; mmCIF/BinaryCIF/PDB.
# Residues use UniProt numbering on AlphaFold models.
# color_by: "auto" | "plddt" | "chain" | "secondary-structure" | "rainbow" | "uniform"

av.variants(df, length=189, domains=[{"start": 32, "end": 40, "name": "Effector"}],
            highlight=[12], labels={12: "G12D"}, title="",
            position="position", label="label", significance="significance")
# df: one row per variant; the three column names are set by the last three
# arguments (e.g. label="variant"). significance: ClinVar wording or P/LP/VUS/LB/B.

av.table(df, links={"ClinVar": "https://www.ncbi.nlm.nih.gov/clinvar/variation/{clinvar_id}/"},
         columns=None, title="", height=420)
# links: column -> URL template filled from the row; an id column used only
# by a template is hidden.
```

Where the data comes from:

| What | Call |
|---|---|
| Gene → UniProt accession | `GET https://rest.uniprot.org/uniprotkb/search?query=gene_exact:{GENE} AND organism_id:9606 AND reviewed:true&fields=accession&format=json` → `results[0].primaryAccession`. Never type an accession from memory without this check (the reference notebook does it) |
| Protein length, domains, function | `GET https://rest.uniprot.org/uniprotkb/{accession}.json` → `sequence.length`, `features` (types Domain, Region, Motif, DNA binding, Zinc finger), `comments[commentType=FUNCTION]`, the gene's HGNC id in `uniProtKBCrossReferences[database=HGNC]` |
| AlphaFold model | `GET https://alphafold.ebi.ac.uk/api/prediction/{accession}` → `[0]["cifUrl"]` (never hard-code the model version) |
| ClinVar variants | `esearch.fcgi?db=clinvar&term={GENE}[gene] AND missense_variant[molecular_consequence]&retmode=json`, paged with `retstart`/`retmax` until `esearchresult.count` ids are in hand (never `single_gene[prop]`: it drops every record that also lists an overlapping locus, e.g. all of BRCA1's exon 11), then `esummary.fcgi?db=clinvar&id=…` (≤ 400 ids per call); check that as many records came back as `count` said. Transcript, gene, c. and p. changes in `title`; keep the records on the gene's reference transcript (MANE Select, the most frequent in the titles). Classes: `germline_classification`, and the somatic ones apart, `oncogenicity_classification` and `clinical_impact_classification` (each with `description`, `review_status`, `last_evaluated`); a record with none has "no classification provided" (evidence-only submissions). GRCh38 position in `variation_set[0].variation_loc`, `canonical_spdi`, dbSNP in `variation_xrefs` |
| One variant's submissions | `efetch.fcgi?db=clinvar&id={variation id}&rettype=vcv&is_variationid` → XML, one `ClinicalAssertion` per submission with its own `Classification`; an expert panel's ACMG criteria are in its `Classification/Comment` |
| Literature | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=…&format=json&sort=CITED desc&resultType=core` → `abstractText`, `isOpenAccess`, `pmcid` (`lite` has no abstract) |
| Full text (open access only) | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML` → JATS XML, `body/sec` with `sec-type` results, discussion. Only when `isOpenAccess == "Y"`: the others fail after seconds |

## Recipe

Read [`references/notebook.py`](references/notebook.py): a complete notebook
(KRAS p.G12D) that runs as is. For another protein, copy its cells and change
the gene, its accession (look it up, see above: a wrong one shows another
protein), the variant and the residue numbers; keep the
structure: question → protein (UniProt) → 3D structure → ClinVar variants
plot and table → literature → **facts** → sources.

The facts cell computes, from the data above, what the answer rests on, and
also `print`s it, so `python notebook.py` shows it to you:

- the region or domain holding the residue;
- the residue's neighbours **in 3D** (an atom within 8 Å in the AlphaFold
  model), the functional sites among them (UniProt binding sites of a
  ligand or a metal ion, catalytic or DNA-contact sites), and the pLDDT at
  the residue and over the model: a neighbourhood or a site counted along
  the sequence misses what folds next to the residue;
- the variant's full nomenclature (HGVS c. and p. on the reference
  transcript, GRCh38 position, SPDI, dbSNP);
- its ClinVar germline classification with review status (stars), last
  evaluation date and conditions, its somatic classifications apart, the
  submissions by class, and an expert panel's ACMG criteria when there is
  one; say what is not there (functional assays in detail);
- how many ClinVar records were found, fetched and kept, and how many have
  no classification;
- how many pathogenic ClinVar variants sit at the same residue. That is
  not a mutational hotspot: a hotspot is somatic recurrence in tumours
  (COSMIC, cancerhotspots.org), which this notebook does not query, so do
  not call the residue a hotspot from this count;
- how many articles mention the variant;
- the gene and the protein, named apart with their identifiers (HGNC,
  UniProt), and UniProt's Function sentence: the definition you give;
- for each paper: what was read (`titre`, `résumé`, `texte intégral`) and
  the sentence that names the variant.

## Answer from the data

Your chat answer states these facts with their numbers and sources, in
French, as found by the notebook — not from memory and not hedged with
"généralement". Add what the literature says and the clinical context (the
conditions ClinVar lists for the variant). Follow the `scientific-rigor`
skill for how to word it.

## Literature: read before you conclude

The literature table has a **« lu »** column (`titre`, `résumé`, `texte
intégral`) and an **Extrait**: the sentence of the abstract that names the
variant and its conclusion, or the sentences of the full text's results and
discussion that name it.

- **Never conclude from a title.** A paper whose « lu » is `titre` is only a
  pointer: list it, claim nothing from it.
- **Say what was read**: « d'après le résumé », « d'après le texte
  intégral (résultats) ».
- **Quote or paraphrase the sentence** that supports a claim, with the
  citation (first author, journal, year, PMID).
- Give the **experimental level** the sentence describes: in vitro, lignée
  cellulaire, souris, cohorte humaine, essai clinique. A mouse result is a
  mouse result.
- A paper you want to cite that the search did not return: fetch it in the
  notebook by PMID (`query=EXT_ID:{pmid} AND SRC:MED`) so its abstract is
  shown too. Never cite from memory.

## Before you end your turn

1. Re-read `notebook.py`: it contains `av.structure(`, `av.variants(` and
   `av.table(`, each the last expression of its cell, and `requests.get`
   calls for the data. If a viewer is missing, add its cell now.
2. Run, from the workspace folder, `marimo check notebook.py` then
   `python notebook.py` (must exit 0). Fix and re-run until both pass.
3. Answer in the chat from the facts `python notebook.py` printed, and
   point to what the notebook shows.
