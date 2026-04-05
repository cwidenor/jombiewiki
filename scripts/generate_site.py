from __future__ import annotations

import html
import json
import os
import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
PACK_PATH = Path(os.environ.get("JOMBIEPACK_PATH", str(CACHE_DIR / "source" / "JombiePack 1.21.1 1.0.0.mrpack")))
PACK_URL = os.environ.get("JOMBIEPACK_URL", "").strip()
DOWNLOAD_DIR = Path(os.environ.get("JOMBIEPACK_DOWNLOAD_DIR", str(CACHE_DIR / "downloaded_jars")))
OVERRIDE_CACHE = CACHE_DIR / "override_jars"
SITE_DIR = ROOT / "site"
ASSETS_DIR = ROOT / "assets"


@dataclass
class Recipe:
    recipe_id: str
    recipe_type: str
    mod_id: str
    outputs: list[dict[str, Any]] = field(default_factory=list)
    pattern: list[str] | None = None
    key: dict[str, Any] = field(default_factory=dict)
    ingredients: list[Any] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ItemEntry:
    item_id: str
    display_name: str
    entry_type: str
    namespace: str
    owner_mod_id: str
    source_jar: str
    icon_path: str = ""
    recipes: list[Recipe] = field(default_factory=list)


@dataclass
class ModEntry:
    mod_id: str
    name: str
    version: str
    description: str
    jar_name: str
    item_ids: list[str] = field(default_factory=list)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-") or "entry"


def safe_text(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def page(title: str, body: str, *, rel_root: str = ".", extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_text(title)}</title>
  <link rel="stylesheet" href="{rel_root}/assets/style.css">
  {extra_head}
</head>
<body>
  <div class="page">
    {body}
    <div class="footer">Generated from JombiePack 1.21.1 1.0.0 pack data.</div>
  </div>
</body>
</html>
"""


def read_json_from_zip(zf: zipfile.ZipFile, name: str) -> Any | None:
    try:
        with zf.open(name) as fh:
            return json.load(fh)
    except Exception:
        return None


def read_text_from_zip(zf: zipfile.ZipFile, name: str) -> str | None:
    try:
        with zf.open(name) as fh:
            return fh.read().decode("utf-8")
    except Exception:
        return None


def ensure_pack_available() -> None:
    if PACK_PATH.exists():
        return
    if not PACK_URL:
        raise FileNotFoundError(
            f"Pack file not found at {PACK_PATH}. Set JOMBIEPACK_PATH or JOMBIEPACK_URL before running the generator."
        )
    PACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(PACK_URL, PACK_PATH)


def download_missing_mod_jars(index_data: dict[str, Any]) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for file_entry in index_data.get("files", []):
        path = file_entry.get("path", "")
        if not path.startswith("mods/"):
            continue
        target = DOWNLOAD_DIR / Path(path).name
        if target.exists():
            continue
        downloads = file_entry.get("downloads") or []
        if not downloads:
            continue
        urllib.request.urlretrieve(downloads[0], target)


def extract_override_jars() -> list[Path]:
    ensure_pack_available()
    OVERRIDE_CACHE.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(PACK_PATH) as pack:
        for info in pack.infolist():
            if not info.filename.startswith("overrides/mods/") or not info.filename.endswith(".jar"):
                continue
            target = OVERRIDE_CACHE / Path(info.filename).name
            if not target.exists():
                with pack.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            extracted.append(target)
    return extracted


def load_pack_index() -> dict[str, Any]:
    ensure_pack_available()
    with zipfile.ZipFile(PACK_PATH) as pack:
        with pack.open("modrinth.index.json") as fh:
            return json.load(fh)


def find_jar_paths(index_data: dict[str, Any]) -> list[Path]:
    jar_paths: list[Path] = []
    seen: set[Path] = set()
    for file_entry in index_data.get("files", []):
        path = file_entry.get("path", "")
        if not path.startswith("mods/"):
            continue
        jar_path = DOWNLOAD_DIR / Path(path).name
        if jar_path.exists() and jar_path not in seen:
            jar_paths.append(jar_path)
            seen.add(jar_path)
    for path in extract_override_jars():
        if path not in seen:
            jar_paths.append(path)
            seen.add(path)
    return jar_paths


def parse_mod_metadata(zf: zipfile.ZipFile, jar_name: str) -> list[ModEntry]:
    neoforge_toml = read_text_from_zip(zf, "META-INF/neoforge.mods.toml")
    if neoforge_toml:
        try:
            data = tomllib.loads(neoforge_toml)
            mods = []
            for mod in data.get("mods", []):
                mod_id = mod.get("modId") or slugify(Path(jar_name).stem)
                mods.append(
                    ModEntry(
                        mod_id=mod_id,
                        name=mod.get("displayName") or mod_id,
                        version=str(mod.get("version", "")),
                        description=(mod.get("description") or "").strip(),
                        jar_name=jar_name,
                    )
                )
            if mods:
                return mods
        except Exception:
            pass

    fabric_json = read_json_from_zip(zf, "fabric.mod.json")
    if fabric_json:
        mod_id = fabric_json.get("id") or slugify(Path(jar_name).stem)
        return [
            ModEntry(
                mod_id=mod_id,
                name=fabric_json.get("name") or mod_id,
                version=str(fabric_json.get("version", "")),
                description=(fabric_json.get("description") or "").strip(),
                jar_name=jar_name,
            )
        ]

    fallback = slugify(Path(jar_name).stem)
    return [ModEntry(mod_id=fallback, name=fallback, version="", description="", jar_name=jar_name)]


def parse_item_language_entries(zf: zipfile.ZipFile, source_mods: list[ModEntry], jar_name: str) -> list[ItemEntry]:
    known_mod_ids = {mod.mod_id for mod in source_mods}
    entries: dict[str, ItemEntry] = {}
    for name in zf.namelist():
        if not name.startswith("assets/") or not name.endswith("/lang/en_us.json"):
            continue
        lang_data = read_json_from_zip(zf, name)
        if not isinstance(lang_data, dict):
            continue
        for key, value in lang_data.items():
            match = re.match(r"^(item|block)\.([a-z0-9_.-]+)\.(.+)$", key)
            if not match:
                continue
            entry_type, namespace, raw_name = match.groups()
            item_id = f"{namespace}:{raw_name}"
            owner_mod_id = namespace if namespace in known_mod_ids else (source_mods[0].mod_id if len(source_mods) == 1 else namespace)
            entries[item_id] = ItemEntry(
                item_id=item_id,
                display_name=str(value),
                entry_type=entry_type,
                namespace=namespace,
                owner_mod_id=owner_mod_id,
                source_jar=jar_name,
            )
    return list(entries.values())


def normalize_item_stack(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"item": raw, "count": 1}
    if isinstance(raw, list):
        for value in raw:
            normalized = normalize_item_stack(value)
            if normalized:
                return normalized
        return None
    if isinstance(raw, dict):
        if "item" in raw:
            item_value = raw["item"]
            if isinstance(item_value, str):
                return {"item": item_value, "count": int(raw.get("count", 1))}
            nested = normalize_item_stack(item_value)
            if nested:
                nested["count"] = int(raw.get("count", nested.get("count", 1)))
                return nested
        if "id" in raw:
            id_value = raw["id"]
            if isinstance(id_value, str):
                return {"item": id_value, "count": int(raw.get("count", 1))}
            nested = normalize_item_stack(id_value)
            if nested:
                nested["count"] = int(raw.get("count", nested.get("count", 1)))
                return nested
        if "result" in raw:
            return normalize_item_stack(raw["result"])
        if "basePredicate" in raw:
            return normalize_item_stack(raw["basePredicate"])
    return None


def normalize_ingredient(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        values = [normalize_ingredient(item) for item in raw]
        return " / ".join(value for value in values if value)
    if isinstance(raw, dict):
        if "item" in raw:
            return raw["item"]
        if "tag" in raw:
            return f"#{raw['tag']}"
        if "items" in raw:
            return normalize_ingredient(raw["items"])
        if "ingredient" in raw:
            return normalize_ingredient(raw["ingredient"])
    return str(raw)


def parse_recipe_data(mod_id: str, recipe_id: str, data: dict[str, Any]) -> Recipe:
    recipe = Recipe(
        recipe_id=recipe_id,
        recipe_type=str(data.get("type", "minecraft:crafting_shaped")),
        mod_id=mod_id,
    )

    outputs: list[dict[str, Any]] = []
    for key in ("result", "results", "output", "outputs"):
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, list):
            outputs.extend(stack for stack in (normalize_item_stack(raw) for raw in value) if stack)
        else:
            stack = normalize_item_stack(value)
            if stack:
                outputs.append(stack)
    recipe.outputs = outputs

    if "pattern" in data:
        recipe.pattern = [str(row) for row in data.get("pattern", [])]
    if "key" in data and isinstance(data["key"], dict):
        recipe.key = {str(k): v for k, v in data["key"].items()}

    if "ingredients" in data and isinstance(data["ingredients"], list):
        recipe.ingredients = list(data["ingredients"])
    elif "ingredient" in data:
        recipe.ingredients = [data["ingredient"]]

    for key in ("category", "experience", "cookingtime", "processingTime", "heatRequirement", "keep_held_item"):
        if key in data:
            recipe.extra[key] = data[key]

    return recipe


def parse_recipes(zf: zipfile.ZipFile, mod_id: str) -> list[Recipe]:
    recipes: list[Recipe] = []
    for name in zf.namelist():
        if not name.startswith("data/") or not name.endswith(".json"):
            continue
        if "/advancement/" in name:
            continue
        if "/recipe/" not in name and "/recipes/" not in name:
            continue
        data = read_json_from_zip(zf, name)
        if not isinstance(data, dict):
            continue
        recipes.append(parse_recipe_data(mod_id, name.removesuffix(".json"), data))
    return recipes


def load_catalog() -> tuple[list[Path], dict[str, ModEntry], dict[str, ItemEntry]]:
    index_data = load_pack_index()
    download_missing_mod_jars(index_data)
    jar_paths = find_jar_paths(index_data)

    mods: dict[str, ModEntry] = {}
    items: dict[str, ItemEntry] = {}

    for jar_path in jar_paths:
        with zipfile.ZipFile(jar_path) as zf:
            source_mods = parse_mod_metadata(zf, jar_path.name)
            for mod in source_mods:
                mods.setdefault(mod.mod_id, mod)

            for item in parse_item_language_entries(zf, source_mods, jar_path.name):
                current = items.get(item.item_id)
                if current is None or len(current.display_name) < len(item.display_name):
                    items[item.item_id] = item

            primary_mod_id = source_mods[0].mod_id
            for recipe in parse_recipes(zf, primary_mod_id):
                for output in recipe.outputs:
                    item_id = output["item"]
                    if item_id not in items:
                        namespace, _, path = item_id.partition(":")
                        owner_mod_id = namespace if namespace in mods else primary_mod_id
                        items[item_id] = ItemEntry(
                            item_id=item_id,
                            display_name=path.replace("_", " ").title(),
                            entry_type="item",
                            namespace=namespace or primary_mod_id,
                            owner_mod_id=owner_mod_id,
                            source_jar=jar_path.name,
                        )
                    items[item_id].recipes.append(recipe)

    for item in items.values():
        mods.setdefault(
            item.owner_mod_id,
            ModEntry(
                mod_id=item.owner_mod_id,
                name=item.owner_mod_id,
                version="",
                description="",
                jar_name=item.source_jar,
            ),
        )
        mods[item.owner_mod_id].item_ids.append(item.item_id)

    for mod in mods.values():
        mod.item_ids = sorted(set(mod.item_ids), key=str.lower)

    return jar_paths, dict(sorted(mods.items())), dict(sorted(items.items()))


def item_url(item_id: str) -> str:
    namespace, _, path = item_id.partition(":")
    return f"items/{slugify(namespace)}/{slugify(path)}.html"


def mod_url(mod_id: str) -> str:
    return f"mods/{slugify(mod_id)}.html"


def candidate_texture_names(item_id: str) -> list[str]:
    namespace, _, path = item_id.partition(":")
    if not namespace or not path:
        return []
    return [
        f"assets/{namespace}/textures/item/{path}.png",
        f"assets/{namespace}/textures/block/{path}.png",
    ]


def extract_item_icons(jar_paths: list[Path], items: dict[str, ItemEntry]) -> None:
    texture_root = SITE_DIR / "assets" / "textures"
    texture_root.mkdir(parents=True, exist_ok=True)

    for jar_path in jar_paths:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            for item in items.values():
                if item.icon_path:
                    continue
                for candidate in candidate_texture_names(item.item_id):
                    if candidate not in names:
                        continue
                    asset_rel = Path(candidate).relative_to("assets")
                    relative = Path("assets") / "textures" / asset_rel.parts[0] / Path(*asset_rel.parts[2:])
                    target = SITE_DIR / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        with zf.open(candidate) as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                    item.icon_path = relative.as_posix()
                    break


def item_icon_html(item_id: str, rel_root: str, items: dict[str, ItemEntry], *, large: bool = False) -> str:
    item = items.get(item_id)
    if not item or not item.icon_path:
        return ""
    size_class = " large" if large else ""
    return f'<img class="icon{size_class}" src="{rel_root}/{safe_text(item.icon_path)}" alt="{safe_text(item.display_name)}">'


def render_slot(label: str, rel_root: str, items: dict[str, ItemEntry]) -> str:
    if not label:
        return '<div class="slot empty">Empty</div>'
    icon = ""
    if re.match(r"^[a-z0-9_.-]+:[a-z0-9_./-]+(?: ×\d+)?$", label):
        item_id = label.split(" ×", 1)[0]
        icon = item_icon_html(item_id, rel_root, items)
    return f'<div class="slot"><div class="slot-content">{icon}<div>{safe_text(label)}</div></div></div>'


def render_stack_label(stack: dict[str, Any]) -> str:
    item_id = stack.get("item", "")
    count = int(stack.get("count", 1))
    return f"{item_id} ×{count}" if count > 1 else str(item_id)


def render_crafting_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry]) -> str:
    pattern = list(recipe.pattern or [])
    while len(pattern) < 3:
        pattern.append("")

    rows = []
    for row in pattern[:3]:
        for char in row.ljust(3)[:3]:
            rows.append("" if char == " " else normalize_ingredient(recipe.key.get(char)))

    output = recipe.outputs[0] if recipe.outputs else {"item": "unknown", "count": 1}
    return f"""
    <div class="recipe-card">
      <div class="recipe-header">
        <strong>{safe_text(recipe.recipe_type)}</strong>
        <span class="muted path">{safe_text(recipe.recipe_id)}</span>
      </div>
      <div class="crafting-layout">
        <div class="craft-grid">{''.join(render_slot(value, rel_root, items) for value in rows)}</div>
        <div class="arrow">&rarr;</div>
        <div class="result-stack">{render_slot(render_stack_label(output), rel_root, items)}</div>
      </div>
    </div>
    """


def render_shapeless_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry]) -> str:
    ingredients = [normalize_ingredient(value) for value in recipe.ingredients][:9]
    while len(ingredients) < 9:
        ingredients.append("")
    output = recipe.outputs[0] if recipe.outputs else {"item": "unknown", "count": 1}
    return f"""
    <div class="recipe-card">
      <div class="recipe-header">
        <strong>{safe_text(recipe.recipe_type)}</strong>
        <span class="muted path">{safe_text(recipe.recipe_id)}</span>
      </div>
      <div class="crafting-layout">
        <div class="craft-grid">{''.join(render_slot(value, rel_root, items) for value in ingredients)}</div>
        <div class="arrow">&rarr;</div>
        <div class="result-stack">{render_slot(render_stack_label(output), rel_root, items)}</div>
      </div>
      <div class="recipe-meta">Shapeless recipe.</div>
    </div>
    """


def render_generic_recipe(recipe: Recipe) -> str:
    outputs = ", ".join(render_stack_label(output) for output in recipe.outputs) or "Unknown"
    ingredients = [normalize_ingredient(value) for value in recipe.ingredients]
    ingredient_html = "".join(f'<span class="chip">{safe_text(value)}</span>' for value in ingredients if value)
    extra = ", ".join(f"{key}={value}" for key, value in recipe.extra.items())
    return f"""
    <div class="recipe-card">
      <div class="recipe-header">
        <strong>{safe_text(recipe.recipe_type)}</strong>
        <span class="muted path">{safe_text(recipe.recipe_id)}</span>
      </div>
      <div><strong>Output:</strong> {safe_text(outputs)}</div>
      <div class="ingredient-list">{ingredient_html or "<span class='muted'>No ingredient data parsed.</span>"}</div>
      <div class="recipe-meta">{safe_text(extra)}</div>
    </div>
    """


def render_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry]) -> str:
    if recipe.pattern:
        return render_crafting_recipe(recipe, rel_root, items)
    if "crafting_shapeless" in recipe.recipe_type:
        return render_shapeless_recipe(recipe, rel_root, items)
    return render_generic_recipe(recipe)


def build_home(mods: dict[str, ModEntry], items: dict[str, ItemEntry]) -> None:
    body = f"""
    <div class="hero">
      <div class="kicker">Generated Catalog</div>
      <h1>JombiePack Item and Mod Catalog</h1>
      <p class="muted">A GitHub Pages-ready site generated from the actual JombiePack archive, mod jars, and bundled overrides.</p>
      <div class="statlist">
        <div class="stat"><span class="label">Mods</span><strong>{len(mods)}</strong></div>
        <div class="stat"><span class="label">Item or Block Entries</span><strong>{len(items)}</strong></div>
      </div>
    </div>

    <div class="panel">
      <h2>Search</h2>
      <input id="search" class="searchbox" placeholder="Search mods, items, or registry ids">
      <div id="results" class="card-grid" style="margin-top:16px;"></div>
    </div>

    <div class="grid cols-2">
      <div class="panel">
        <h2>Browse</h2>
        <p><a href="mods/index.html">All mods</a></p>
        <p><a href="items/index.html">All items and block entries</a></p>
      </div>
      <div class="panel">
        <h2>Notes</h2>
        <p class="muted">Crafting-table style layouts are rendered for shaped and shapeless crafting data when the recipe JSON exposes that structure directly. Other recipe types are listed as machine or processing recipes.</p>
      </div>
    </div>

    <script src="assets/search.js"></script>
    <script>setupSearch("search", "results", "assets/search-index.json");</script>
    """
    (SITE_DIR / "index.html").write_text(page("JombiePack Catalog", body), encoding="utf-8")


def build_mod_index(mods: dict[str, ModEntry]) -> None:
    mod_dir = SITE_DIR / "mods"
    mod_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for mod in mods.values():
        rows.append(
            f"<tr><td><a href='{safe_text(slugify(mod.mod_id))}.html'>{safe_text(mod.name)}</a></td>"
            f"<td class='path'>{safe_text(mod.mod_id)}</td><td>{len(mod.item_ids)}</td></tr>"
        )
    body = f"""
    <div class="breadcrumbs"><a href="../index.html">Home</a> / Mods</div>
    <div class="panel">
      <h1>Mods</h1>
      <table class="list-table">
        <thead><tr><th>Name</th><th>Mod ID</th><th>Entries</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """
    (mod_dir / "index.html").write_text(page("Mods", body, rel_root=".."), encoding="utf-8")


def build_mod_pages(mods: dict[str, ModEntry], items: dict[str, ItemEntry]) -> None:
    mod_dir = SITE_DIR / "mods"
    mod_dir.mkdir(parents=True, exist_ok=True)
    for mod in mods.values():
        cards = []
        for item_id in mod.item_ids:
            item = items[item_id]
            icon = item_icon_html(item.item_id, "..", items)
            cards.append(
                f"""
                <div class="card">
                  <div class="kicker">{safe_text(item.entry_type)}</div>
                  <div class="entry-head">
                    {icon}
                    <h3><a href="../{safe_text(item_url(item.item_id))}">{safe_text(item.display_name)}</a></h3>
                  </div>
                  <div class="path">{safe_text(item.item_id)}</div>
                  <div class="muted">{len(item.recipes)} recipe(s)</div>
                </div>
                """
            )
        description = safe_text(mod.description) if mod.description else "No description was extracted from the jar metadata."
        body = f"""
        <div class="breadcrumbs"><a href="../index.html">Home</a> / <a href="index.html">Mods</a> / {safe_text(mod.mod_id)}</div>
        <div class="hero">
          <div class="kicker">Mod Page</div>
          <h1>{safe_text(mod.name)}</h1>
          <div class="chips">
            <span class="chip">Mod ID: {safe_text(mod.mod_id)}</span>
            <span class="chip">Version: {safe_text(mod.version or "unknown")}</span>
            <span class="chip">Entries: {len(mod.item_ids)}</span>
          </div>
          <p class="muted">{description}</p>
        </div>
        <div class="panel">
          <h2>Items and Blocks</h2>
          <div class="card-grid">
            {''.join(cards) or "<p class='muted'>No localized item entries were found for this mod yet.</p>"}
          </div>
        </div>
        """
        (mod_dir / f"{slugify(mod.mod_id)}.html").write_text(page(f"{mod.name} - JombiePack", body, rel_root=".."), encoding="utf-8")


def build_item_index(items: dict[str, ItemEntry]) -> None:
    item_dir = SITE_DIR / "items"
    item_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in items.values():
        rows.append(
            f"<tr><td><a href='{safe_text(item.namespace)}/{safe_text(slugify(item.item_id.split(':', 1)[1]))}.html'>{safe_text(item.display_name)}</a></td>"
            f"<td class='path'>{safe_text(item.item_id)}</td>"
            f"<td><a href='../mods/{safe_text(slugify(item.owner_mod_id))}.html'>{safe_text(item.owner_mod_id)}</a></td>"
            f"<td>{len(item.recipes)}</td></tr>"
        )
    body = f"""
    <div class="breadcrumbs"><a href="../index.html">Home</a> / Items</div>
    <div class="panel">
      <h1>Items and Block Entries</h1>
      <table class="list-table">
        <thead><tr><th>Name</th><th>Registry ID</th><th>Mod</th><th>Recipes</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """
    (item_dir / "index.html").write_text(page("Items", body, rel_root=".."), encoding="utf-8")


def build_item_pages(mods: dict[str, ModEntry], items: dict[str, ItemEntry]) -> None:
    item_root = SITE_DIR / "items"
    item_root.mkdir(parents=True, exist_ok=True)
    for item in items.values():
        namespace, _, path = item.item_id.partition(":")
        item_dir = item_root / slugify(namespace)
        item_dir.mkdir(parents=True, exist_ok=True)
        recipes_html = "".join(render_recipe(recipe, "../..", items) for recipe in item.recipes)
        icon = item_icon_html(item.item_id, "../..", items, large=True)
        body = f"""
        <div class="breadcrumbs"><a href="../../index.html">Home</a> / <a href="../index.html">Items</a> / {safe_text(item.item_id)}</div>
        <div class="hero">
          <div class="kicker">{safe_text(item.entry_type)}</div>
          <div class="entry-head">
            {icon}
            <h1>{safe_text(item.display_name)}</h1>
          </div>
          <div class="chips">
            <span class="chip path">{safe_text(item.item_id)}</span>
            <span class="chip">Mod: <a href="../../mods/{safe_text(slugify(item.owner_mod_id))}.html">{safe_text(mods[item.owner_mod_id].name)}</a></span>
            <span class="chip">Recipe count: {len(item.recipes)}</span>
          </div>
        </div>
        <div class="panel">
          <h2>Recipes</h2>
          {recipes_html or "<p class='muted'>No recipe output was found in the scanned data for this entry.</p>"}
        </div>
        """
        (item_dir / f"{slugify(path)}.html").write_text(page(f"{item.display_name} - JombiePack", body, rel_root="../.."), encoding="utf-8")


def build_search_index(mods: dict[str, ModEntry], items: dict[str, ItemEntry]) -> None:
    entries = []
    for mod in mods.values():
        entries.append({"title": mod.name, "kind": "mod", "mod": mod.mod_id, "id": mod.mod_id, "url": mod_url(mod.mod_id)})
    for item in items.values():
        entries.append({"title": item.display_name, "kind": item.entry_type, "mod": item.owner_mod_id, "id": item.item_id, "url": item_url(item.item_id)})
    asset_dir = SITE_DIR / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "search-index.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")


def copy_assets() -> None:
    target = SITE_DIR / "assets"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ASSETS_DIR / "style.css", target / "style.css")
    shutil.copy2(ASSETS_DIR / "search.js", target / "search.js")


def main() -> None:
    jar_paths, mods, items = load_catalog()
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    copy_assets()
    extract_item_icons(jar_paths, items)
    build_home(mods, items)
    build_mod_index(mods)
    build_mod_pages(mods, items)
    build_item_index(items)
    build_item_pages(mods, items)
    build_search_index(mods, items)
    print(f"Generated {len(mods)} mod pages and {len(items)} item pages in {SITE_DIR}")


if __name__ == "__main__":
    main()
