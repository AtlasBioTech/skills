import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    from Bio.PDB import MMCIFParser, NeighborSearch
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    from Bio.SeqUtils import seq1

    import atlas_hub as hub
    import atlas_viewers as av

    return MMCIF2Dict, MMCIFParser, NeighborSearch, av, hub, mo, pd, seq1


@app.cell
def _(mo):
    mo.md("""
    # Interface RBD du SARS-CoV-2 / ACE2, à partir du hub Atlas

    Données du hub Atlas, interrogé en direct : la structure 6M0J du jeu
    *Protein Data Bank*, et le jeu *MoleculeNet BBBP*.
    """)
    return


@app.cell
def _(hub, mo):
    # Search with catalogue words (a database, an organism, a modality): the
    # hub indexes names, tags and descriptions, not the files, so "ACE2" or
    # "6M0J" find nothing.
    try:
        found = hub.search("protein data bank", kind="dataset")
    except (hub.HubError, OSError) as _err:
        found = hub.Entries()
        _out = mo.callout(mo.md(f"Hub injoignable : {_err}"), kind="danger")
    else:
        _out = mo.vstack([mo.md("**Recherche « protein data bank » dans le hub**"), found])
    _out
    return (found,)


@app.cell
def _(hub, mo):
    # The entries the analysis uses, each shown as its card (a link to its
    # page on the hub), with its files.
    try:
        pdb = hub.entry("protein-ml/protein-data-bank")
        bbbp = hub.entry("chem-ml/moleculenet-bbbp")
        _files = pdb.files()
    except (hub.HubError, OSError) as _err:
        pdb = bbbp = None
        _out = mo.callout(mo.md(f"Entrée du hub indisponible : {_err}"), kind="danger")
    else:
        _out = mo.vstack([pdb, mo.md("Fichiers : " + ", ".join(f"`{f.path}`" for f in _files))])
    _out
    return bbbp, pdb


@app.cell
def _(mo):
    mo.md("""
    ## 1. La structure 6M0J
    """)
    return


@app.cell
def _(MMCIF2Dict, MMCIFParser, hub, mo, pdb):
    # The file, downloaded once and cached: hub.download returns a local path.
    mo.stop(pdb is None, mo.callout(mo.md("Entrée PDB indisponible : structure non chargée."), kind="warn"))
    try:
        cif_path = pdb.download("6m0j.cif")
    except (hub.HubError, OSError) as _err:
        cif_path = None
    mo.stop(cif_path is None, mo.callout(mo.md("Téléchargement de `6m0j.cif` impossible."), kind="danger"))
    structure = MMCIFParser(QUIET=True).get_structure("6M0J", str(cif_path))

    # What the file says about itself (title, method, resolution, chains,
    # primary citation): the facts come from the file, not from memory.
    _cif = MMCIF2Dict(str(cif_path))

    def _one(key):
        _v = _cif.get(key, ["?"])
        return _v[0] if isinstance(_v, list) else _v

    _entities = dict(zip(_cif["_entity.id"], _cif["_entity.pdbx_description"]))
    chains = dict(zip(_cif["_pdbx_poly_seq_scheme.pdb_strand_id"], (_entities[e] for e in _cif["_pdbx_poly_seq_scheme.entity_id"])))
    header = {
        "titre": _one("_struct.title"),
        "méthode": _one("_exptl.method"),
        "résolution (Å)": _one("_refine.ls_d_res_high"),
        "article": f"{_one('_citation.title')} {_one('_citation.journal_abbrev')} ({_one('_citation.year')}), doi:{_one('_citation.pdbx_database_id_DOI')}",
    }
    mo.md(
        "\n".join(f"- **{_k}** : {_v}" for _k, _v in header.items())
        + "\n- **chaînes** : " + ", ".join(f"{_c} = {_d}" for _c, _d in chains.items())
    )
    return chains, cif_path, header, structure


@app.cell
def _(NeighborSearch, pd, seq1, structure):
    # The interface, computed: residues of one chain with a heavy atom within
    # 4 Å of the other chain (a usual contact cut-off).
    CUTOFF = 4.0
    ACE2, RBD = "A", "E"
    _atoms = [_a for _a in structure[0].get_atoms() if _a.element != "H" and _a.get_parent().id[0] == " "]
    _contacts = set()
    for _pair in NeighborSearch(_atoms).search_all(CUTOFF):
        if {_x.get_parent().get_parent().id for _x in _pair} == {ACE2, RBD}:
            for _x in _pair:
                _res = _x.get_parent()
                _contacts.add((_res.get_parent().id, _res.id[1], seq1(_res.get_resname())))
    interface = pd.DataFrame(sorted(_contacts), columns=["chaîne", "résidu", "aa"])
    interface["protéine"] = interface["chaîne"].map({ACE2: "ACE2", RBD: "RBD (Spike)"})
    interface["nom"] = interface["aa"] + interface["résidu"].astype(str)
    rbd_contacts = interface[interface["chaîne"] == RBD]
    return ACE2, CUTOFF, RBD, interface, rbd_contacts


@app.cell
def _(RBD, av, cif_path, rbd_contacts):
    # Mol*: the RBD's interface residues as magenta side chains, coloured by
    # chain. The labels name a few of them (from the table, not typed).
    _named = rbd_contacts[rbd_contacts["résidu"].isin([417, 493, 501, 505])]
    av.structure(
        cif_path,
        chain=RBD,
        highlight=rbd_contacts["résidu"].tolist(),
        labels=dict(zip(_named["résidu"], _named["nom"])),
        color_by="chain",
        title="6M0J : RBD de Spike (chaîne E) lié à ACE2 (chaîne A)",
        subtitle="En magenta : résidus du RBD à moins de 4 Å d'ACE2",
    )
    return


@app.cell
def _(av, interface):
    av.table(interface[["protéine", "chaîne", "nom", "résidu"]], title="Résidus de l'interface (contact ≤ 4 Å)", height=320)
    return


@app.cell
def _(mo):
    mo.md("""
    ## 2. Un jeu tabulaire du hub : MoleculeNet BBBP
    """)
    return


@app.cell
def _(bbbp, hub, mo):
    # A table straight into pandas (downloaded and cached like any file).
    mo.stop(bbbp is None, mo.callout(mo.md("Entrée BBBP indisponible."), kind="warn"))
    try:
        molecules = bbbp.read_table("bbbp.csv")
    except (hub.HubError, OSError) as _err:
        molecules = None
    mo.stop(molecules is None, mo.callout(mo.md("Lecture de `bbbp.csv` impossible."), kind="danger"))
    # Columns on this hub: SMILES, label (1 = crosses the blood-brain barrier).
    bbbp_summary = {
        "molécules": len(molecules),
        "colonnes": ", ".join(molecules.columns),
        "label 1 (franchit la BHE)": int((molecules["label"] == 1).sum()),
        "label 0": int((molecules["label"] == 0).sum()),
    }
    mo.vstack([bbbp, mo.md("\n".join(f"- **{_k}** : {_v}" for _k, _v in bbbp_summary.items())), molecules.head(5)])
    return (bbbp_summary,)


@app.cell
def _(CUTOFF, bbbp, bbbp_summary, chains, header, interface, mo, pdb, rbd_contacts):
    # What the answer rests on, printed too, so `python notebook.py` shows it.
    facts = [
        f"Entrée du hub : {pdb.display_name} — {pdb.url}",
        f"Structure 6M0J : {header['titre']} ; {header['méthode']}, {header['résolution (Å)']} Å",
        "Chaînes : " + " ; ".join(f"{_c} = {_d}" for _c, _d in chains.items()),
        f"Interface (≤ {CUTOFF} Å) : {len(rbd_contacts)} résidus du RBD, {len(interface) - len(rbd_contacts)} d'ACE2",
        "Résidus du RBD au contact : " + ", ".join(rbd_contacts["nom"]),
        f"Article de la structure : {header['article']}",
        f"Entrée du hub : {bbbp.display_name} — {bbbp.url}",
        f"BBBP : {bbbp_summary['molécules']} molécules, {bbbp_summary['label 1 (franchit la BHE)']} label 1, {bbbp_summary['label 0']} label 0",
    ]
    print("\n".join(facts))
    mo.md("## Faits\n\n" + "\n".join(f"- {_f}" for _f in facts))
    return


@app.cell
def _(bbbp, mo, pdb):
    mo.md(f"""
    ## Sources

    - [{pdb.display_name}]({pdb.url}) (hub Atlas), fichier `6m0j.cif`
    - [{bbbp.display_name}]({bbbp.url}) (hub Atlas), fichier `bbbp.csv`
    - Fiche RCSB de 6M0J : https://www.rcsb.org/structure/6M0J
    """)
    return


if __name__ == "__main__":
    app.run()
