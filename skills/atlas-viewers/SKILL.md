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
| Protein length, domains, function | `GET https://rest.uniprot.org/uniprotkb/{accession}.json` → `sequence.length`, `features` (types Domain, Region, Motif, DNA binding, Zinc finger) |
| AlphaFold model | `GET https://alphafold.ebi.ac.uk/api/prediction/{accession}` → `[0]["cifUrl"]` (never hard-code the model version) |
| ClinVar variants | `esearch.fcgi?db=clinvar&term={GENE}[gene] AND single_gene[prop] AND missense_variant[molecular_consequence]&retmode=json`, then `esummary.fcgi?db=clinvar&id=…` (≤ 400 ids per call); protein change in `title`, class in `germline_classification.description` |
| Literature | `GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=…&format=json&sort=CITED desc` |

## Recipe

Read [`references/notebook.py`](references/notebook.py): a complete notebook
(KRAS p.G12D) that runs as is. For another protein, copy its cells and change
the accession, the gene, the variant and the residue numbers; keep the
structure: question → protein (UniProt) → 3D structure → ClinVar variants
plot and table → literature → sources.

## Before you end your turn

1. Re-read `notebook.py`: it contains `av.structure(`, `av.variants(` and
   `av.table(`, each the last expression of its cell, and `requests.get`
   calls for the data. If a viewer is missing, add its cell now.
2. Run, from the workspace folder, `marimo check notebook.py` then
   `python notebook.py` (must exit 0). Fix and re-run until both pass.
3. Answer in the chat and point to what the notebook shows.
