# JombiePack Catalog Site

This repo is a generated, GitHub Pages-friendly catalog for **JombiePack 1.21.1 1.0.0**.

It is designed for large-scale modpacks where you want:

- one page per mod
- one page per item or block entry
- recipe sections on item pages
- a structure that can be regenerated when the pack updates

## Why this is not a GitHub Wiki

GitHub Wikis are fine for hand-written articles, but they are awkward for:

- thousands of generated pages
- shared styling for Minecraft-like recipe layouts
- client-side search and navigation helpers
- rebuilding the whole site from pack data

This repo is meant to be pushed to GitHub and published with **GitHub Pages** instead.

## Layout

- `scripts/generate_site.py` reads the `.mrpack`, downloaded jars, and bundled override jars
- `site/` contains the generated static output
- `cache/override_jars/` stores extracted override jars from the `.mrpack`
- `runtime-data/` stores exported live item and block properties for the wiki

## Regenerating

From this folder:

```powershell
python .\scripts\generate_site.py
```

If you have exported live runtime data from the helper extractor mod, put:

- `items.json`
- `blocks.json`
- `manifest.json`

inside `runtime-data/`.

The generator will automatically add a `Properties` section to item and block pages when those files are present.

## Pack Source

The generator supports two ways to get the `.mrpack`:

1. Put the pack at `cache/source/JombiePack 1.21.1 1.0.0.mrpack`
2. Set `JOMBIEPACK_URL` to a direct download URL and let the generator download it

The generator then downloads the referenced mod jars into `cache/downloaded_jars` automatically and extracts bundled override jars into `cache/override_jars`.

## Output

Open:

- `site\index.html`
- `site\mods\index.html`
- `site\items\index.html`

Then publish the contents of `site/` on GitHub Pages.

## GitHub Pages

This repo includes a GitHub Actions workflow that:

- builds the site on pushes to `main`
- uploads the generated `site/` folder as a Pages artifact
- deploys it to GitHub Pages

### Recommended setup

1. Create a GitHub repo from this folder.
2. In the repo settings, enable **GitHub Pages** with **GitHub Actions** as the source.
3. Add a repository variable or secret named `JOMBIEPACK_URL` if the pack file is not committed locally.
4. Push to `main`.

## Repository Notes

- `site/` is generated output
- `cache/` is ignored and can be rebuilt
- `runtime-data/` should be committed if you want GitHub Pages builds to include live property data
- `.github/workflows/deploy.yml` contains the deploy workflow
