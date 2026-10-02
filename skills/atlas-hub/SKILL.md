---
name: atlas-hub
description: Search the Atlas hub (the organisation's catalogue of models, datasets, notebooks, benchmarks and papers) and load its files in a marimo notebook with atlas_hub (hub.search, hub.entry, hub.download, hub.read_table). Use when the question names a model, a dataset, a structure, a benchmark or "le hub", or needs reference data (a PDB structure, a genome, a molecule table) - before the open web.
---

# The Atlas hub in a notebook

The hub (`$ATLAS_API_URL`, by default https://demoatlas.online) is the
organisation's catalogue. When the question names a model, a dataset, a
structure, a benchmark or the hub, or needs reference data, **look in the hub
first**, then use the public databases for what it does not have.

## 1. Search (one shell command, or a cell)

```sh
python -m atlas_hub search protein data bank --json        # --kind dataset|model|notebook|benchmark|paper
python -m atlas_hub show protein-ml/protein-data-bank --json   # description, tags, files
```

- Search covers **names, tags and descriptions, not file contents**: a gene,
  a protein or a PDB id ("ACE2", "6M0J") finds nothing. Search with
  **catalogue words**: the database or dataset name ("protein data bank",
  "moleculenet", "bbbp"), the organism ("sars"), the modality ("structure",
  "genome"). If a search is empty, **retry with a simpler, broader word**
  before concluding the hub has nothing; then say what you searched.
- `show` lists the entry's files: pick the file from there, never guess a path.

## 2. Cite what you used

Every hub entry you used goes in the answer as a **markdown link to its page
URL**, exactly the `url` that `search`/`show` returned (the chat shows it as
a chip):

```markdown
D'après la structure 6M0J du jeu [Protein Data Bank](https://demoatlas.online/datasets/protein-ml/protein-data-bank) du hub Atlas…
```

Never build or invent a hub URL; cite only entries the hub returned.

## 3. Load files in notebook cells, not in the shell

```python
import atlas_hub as hub

found = hub.search("protein data bank", kind="dataset") # list of Entry (.display_name, .url, .ref)
pdb = hub.entry("protein-ml/protein-data-bank")         # its card: last expression of a cell
path = pdb.download("6m0j.cif")                          # local pathlib.Path, cached
df = hub.read_table("chem-ml/moleculenet-bbbp", "bbbp.csv")   # csv/tsv/parquet → DataFrame
```

- `download` returns a **local path**: give it to `av.structure(path, …)`
  (skill `atlas-viewers`), Biopython, pandas. Don't re-download with
  `requests`, and don't use `/files/raw/` URLs in the notebook.
- Show each entry you use **once** with its card (`pdb` as the last
  expression, or `mo.vstack([pdb, …])`) near the cell that uses its data: the
  reader sees where the data comes from. List search results as links.
- Wrap hub calls in `try/except (hub.HubError, OSError)` and show a
  `mo.callout`; `mo.stop` the cells that need the file.
- Public entries need no token. `hub.NotFound` on an entry you found by search
  means it is private: say so, don't work around it.
- The hub is read-only for you: never publish, create or modify hub entries.

## Recipe

[`references/notebook.py`](references/notebook.py) runs as is: search (a
list) → the entry's card → `6m0j.cif` downloaded → the RBD/ACE2 interface
computed with Biopython (contacts ≤ 4 Å) → Mol* view with the interface
highlighted → the `bbbp.csv` table summarised → a **facts** cell that
`print`s what the answer rests on (with the hub URLs) → sources. Copy its
cells for another entry.

The files on the demo hub: `protein-ml/protein-data-bank` (`6m0j.cif`,
`1igt.cif`), `chem-ml/moleculenet-bbbp` (`bbbp.csv`: columns `SMILES`,
`label`), `genomics/sars-cov-2-wuhan-hu-1` (`wuhCor1.fa.gz`).
