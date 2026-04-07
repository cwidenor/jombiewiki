from __future__ import annotations

import html
import json
import os
import re
import shutil
import hashlib
import base64
import urllib.parse
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
MINECRAFT_CACHE = CACHE_DIR / "minecraft"


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
    usages: list[Recipe] = field(default_factory=list)


@dataclass
class ModEntry:
    mod_id: str
    name: str
    version: str
    description: str
    jar_name: str
    modrinth_project_id: str = ""
    modrinth_slug: str = ""
    modrinth_url: str = ""
    modrinth_icon_url: str = ""
    modrinth_icon_path: str = ""
    project_summary: str = ""
    project_body: str = ""
    categories: list[str] = field(default_factory=list)
    client_side: str = ""
    server_side: str = ""
    downloads: int = 0
    issues_url: str = ""
    source_url: str = ""
    wiki_url: str = ""
    discord_url: str = ""
    item_ids: list[str] = field(default_factory=list)
    docs_excerpt: str = ""
    docs_points: list[str] = field(default_factory=list)
    docs_source_url: str = ""


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-") or "entry"


def safe_text(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def lowered_keys(raw: dict[str, Any]) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in raw.items()}


def fallback_display_name(item_id: str) -> str:
    _, _, path = item_id.partition(":")
    base = path.split("/")[-1]
    return base.replace("_", " ").replace("-", " ").title()


def normalize_display_name(item_id: str, raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return fallback_display_name(item_id)
    if "%s" in value or "%1$s" in value or "%2$s" in value:
        return fallback_display_name(item_id)
    return value


def friendly_tag_name(tag: str) -> str:
    cleaned = tag.lstrip("#")
    namespace, _, path = cleaned.partition(":")
    namespace = namespace or ""
    path_parts = [part for part in path.split("/") if part]
    if not path_parts:
        return tag

    def titleize(value: str) -> str:
        return " ".join(part.capitalize() for part in value.replace("_", " ").replace("-", " ").split())

    if len(path_parts) >= 2:
        category = path_parts[0]
        material = titleize(" ".join(path_parts[1:]))
        singular_map = {
            "ingots": "Ingot",
            "nuggets": "Nugget",
            "dusts": "Dust",
            "gems": "Gem",
            "plates": "Plate",
            "rods": "Rod",
            "gears": "Gear",
            "storage_blocks": "Storage Block",
            "ores": "Ore",
            "raw_materials": "Raw Material",
        }
        if category in singular_map:
            return f"Any {material} {singular_map[category]}".strip()

    simple_map = {
        "strings": "Any String",
        "ropes": "Any Rope",
        "trim_materials": "Any Trim Material",
        "trimmable_armor": "Any Trimmable Armor Piece",
        "planks": "Any Planks",
        "logs": "Any Log",
        "wools": "Any Wool",
        "stone": "Any Stone",
    }
    joined = "_".join(path_parts)
    if joined in simple_map:
        return simple_map[joined]

    titled = titleize(" ".join(path_parts))
    if namespace in {"c", "forge"}:
        return f"Any {titled}".strip()
    return f"Tag: {titleize(namespace)} {titled}".strip()


def friendly_stack_label(stack: dict[str, Any], items: dict[str, ItemEntry]) -> str:
    item_id = str(stack.get("item", ""))
    count = int(stack.get("count", 1))
    base = item_id
    if item_id.startswith("#"):
        base = friendly_tag_name(item_id)
    elif item_id in items:
        base = items[item_id].display_name
    elif ":" in item_id:
        base = fallback_display_name(item_id)
    label = f"{base} ×{count}" if count > 1 else base
    if "chance" in stack:
        try:
            label += f" ({float(stack['chance'])*100:.0f}%)"
        except Exception:
            pass
    return label


def friendly_ingredient_label(value: str, items: dict[str, ItemEntry]) -> str:
    if not value:
        return value
    if value.startswith("#"):
        return friendly_tag_name(value)
    if value in items:
        return items[value].display_name
    if ":" in value:
        return fallback_display_name(value)
    return value


def is_internal_item_name(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.startswith("example")
        or lowered.startswith("test_")
        or lowered.startswith("debug_")
        or lowered.startswith("dev_")
        or "/example" in lowered
        or "_example" in lowered
    )


def page(title: str, body: str, *, rel_root: str = ".", extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_text(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      theme: {{
        extend: {{
          colors: {{
            slatebrand: {{
              50: '#f8fafc',
              100: '#f1f5f9',
              200: '#e2e8f0',
              300: '#cbd5e1',
              400: '#94a3b8',
              500: '#64748b',
              600: '#475569',
              700: '#334155',
              800: '#1e293b',
              900: '#0f172a'
            }},
            ember: '#f97316',
            moss: '#16a34a'
          }},
          boxShadow: {{
            panel: '0 24px 70px rgba(15, 23, 42, 0.16)'
          }}
        }}
      }}
    }}
  </script>
  <link rel="stylesheet" href="{rel_root}/assets/style.css">
  {extra_head}
</head>
<body class="min-h-screen bg-slatebrand-950 text-slate-100">
  <div class="site-shell">
    <header class="site-header">
      <div class="page header-inner">
        <a class="brand" href="{rel_root}/index.html">
          <span class="brand-mark">J</span>
          <span>
            <strong>JombiePack Wiki</strong>
            <span class="brand-sub">Catalog, recipes, and mod docs</span>
          </span>
        </a>
        <nav class="header-nav">
          <a href="{rel_root}/index.html">Home</a>
          <a href="{rel_root}/mods/index.html">Mods</a>
          <a href="{rel_root}/items/index.html">Items</a>
        </nav>
      </div>
    </header>
    <main class="page page-main">
      {body}
    </main>
    <footer class="page footer">Generated from JombiePack 1.21.1 1.0.0 pack data.</footer>
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


def fetch_json(url: str) -> Any | None:
    request = urllib.request.Request(url, headers={"User-Agent": "jombiewiki-generator/1.0"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except Exception:
        return None


def download_file(url: str, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "jombiewiki-generator/1.0"})
    try:
        with urllib.request.urlopen(request) as response, target.open("wb") as fh:
            shutil.copyfileobj(response, fh)
        return True
    except Exception:
        return False


def strip_markdown(text: str, *, limit: int = 420) -> str:
    cleaned = html.unescape(text or "")
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</p\s*>", "\n\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"[*_>#-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit].rsplit(" ", 1)[0] + "..." if len(cleaned) > limit else cleaned


def cache_path_for_url(url: str, suffix: str = ".txt") -> Path:
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / "doc_pages" / f"{key}{suffix}"


def fetch_text(url: str) -> str:
    cache_file = cache_path_for_url(url)
    if cache_file.exists():
        try:
            return cache_file.read_text(encoding="utf-8")
        except Exception:
            pass
    request = urllib.request.Request(url, headers={"User-Agent": "jombiewiki-generator/1.0"})
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read().decode("utf-8", errors="ignore")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(raw, encoding="utf-8")
        return raw
    except Exception:
        return ""


def extract_sentences(text: str, *, limit: int = 5) -> list[str]:
    cleaned = strip_markdown(text, limit=4000)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences: list[str] = []
    for part in parts:
        normalized = part.strip(" -\n\t")
        if len(normalized) < 35:
            continue
        if normalized.lower().startswith(("download", "installation requirements", "our patrons")):
            continue
        if normalized not in sentences:
            sentences.append(normalized)
        if len(sentences) >= limit:
            break
    return sentences


def summarize_doc_html(raw_html: str) -> tuple[str, list[str]]:
    if not raw_html:
        return "", []
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    title = strip_markdown(title_match.group(1), limit=120) if title_match else ""
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    body = "\n\n".join(strip_markdown(paragraph, limit=500) for paragraph in paragraphs[:12])
    points = extract_sentences(body, limit=4)
    excerpt = points[0] if points else title
    return excerpt, points


def enrich_mod_docs(mods: dict[str, ModEntry]) -> None:
    for mod in mods.values():
        candidates = [url for url in (mod.wiki_url, mod.source_url) if url and "github.com" not in url.lower()]
        excerpt = ""
        points: list[str] = []
        source_url = ""
        for candidate in candidates:
            raw = fetch_text(candidate)
            excerpt, points = summarize_doc_html(raw)
            if excerpt or points:
                source_url = candidate
                break
        if not excerpt:
            fallback_source = mod.wiki_url or mod.modrinth_url
            excerpt = mod.project_summary or mod.description
            points = extract_sentences(mod.project_body or mod.project_summary or mod.description, limit=4)
            source_url = fallback_source or ""
        mod.docs_excerpt = excerpt
        mod.docs_points = points
        mod.docs_source_url = source_url


def parse_modrinth_project_id(download_url: str) -> str:
    match = re.search(r"/data/([A-Za-z0-9]{8})/", download_url or "")
    return match.group(1) if match else ""


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


def pack_minecraft_version(index_data: dict[str, Any]) -> str:
    deps = index_data.get("dependencies", {})
    if isinstance(deps, dict) and isinstance(deps.get("minecraft"), str):
        return deps["minecraft"]
    return "1.21.1"


def local_version_json_candidates(version: str) -> list[Path]:
    env_path = os.environ.get("MINECRAFT_VERSION_JSON", "").strip()
    candidates = [
        Path(env_path) if env_path else None,
        Path(f"C:/Users/chris/curseforge/minecraft/Install/versions/{version}/{version}.json"),
        Path(f"C:/Users/chris/AppData/Roaming/.minecraft/versions/{version}/{version}.json"),
    ]
    return [path for path in candidates if path]


def local_client_jar_candidates(version: str) -> list[Path]:
    env_path = os.environ.get("MINECRAFT_CLIENT_JAR", "").strip()
    candidates = [
        Path(env_path) if env_path else None,
        Path(f"C:/Users/chris/curseforge/minecraft/Install/versions/{version}/{version}.jar"),
        Path(f"C:/Users/chris/AppData/Roaming/.minecraft/versions/{version}/{version}.jar"),
        MINECRAFT_CACHE / version / f"{version}.jar",
    ]
    return [path for path in candidates if path]


def fetch_minecraft_version_metadata(version: str) -> dict[str, Any] | None:
    for candidate in local_version_json_candidates(version):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
    manifest = fetch_json("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json")
    if not isinstance(manifest, dict):
        return None
    versions = manifest.get("versions", [])
    if not isinstance(versions, list):
        return None
    match = next((entry for entry in versions if isinstance(entry, dict) and entry.get("id") == version), None)
    if not isinstance(match, dict) or not isinstance(match.get("url"), str):
        return None
    data = fetch_json(match["url"])
    return data if isinstance(data, dict) else None


def ensure_minecraft_client_jar(version: str) -> Path | None:
    for candidate in local_client_jar_candidates(version):
        if candidate.exists():
            return candidate
    metadata = fetch_minecraft_version_metadata(version)
    if not isinstance(metadata, dict):
        return None
    downloads = metadata.get("downloads", {})
    if not isinstance(downloads, dict):
        return None
    client = downloads.get("client", {})
    if not isinstance(client, dict) or not isinstance(client.get("url"), str):
        return None
    target = MINECRAFT_CACHE / version / f"{version}.jar"
    if target.exists() or download_file(client["url"], target):
        return target
    return None


def load_modrinth_projects(project_ids: list[str]) -> dict[str, dict[str, Any]]:
    cache_file = CACHE_DIR / "modrinth_projects.json"
    cache: dict[str, dict[str, Any]] = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    missing = [project_id for project_id in project_ids if project_id and project_id not in cache]
    for start in range(0, len(missing), 50):
        batch = missing[start:start + 50]
        if not batch:
            continue
        query = urllib.parse.quote(json.dumps(batch))
        url = f"https://api.modrinth.com/v2/projects?ids={query}"
        data = fetch_json(url)
        if not isinstance(data, list):
            continue
        for project in data:
            if isinstance(project, dict) and project.get("id"):
                cache[project["id"]] = project

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return {project_id: cache[project_id] for project_id in project_ids if project_id in cache}


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
    primary_mod_id = source_mods[0].mod_id if source_mods else ""
    entries: dict[str, ItemEntry] = {}
    for name in zf.namelist():
        if not name.startswith("assets/") or not name.endswith("/lang/en_us.json"):
            continue
        lang_data = read_json_from_zip(zf, name)
        if not isinstance(lang_data, dict):
            continue
        for key, value in lang_data.items():
            match = re.match(r"^(item|block)\.([a-z0-9_-]+)\.(.+)$", key)
            if not match:
                continue
            entry_type, namespace, raw_name = match.groups()
            if not re.fullmatch(r"[a-z0-9_/-]+", raw_name):
                continue
            if namespace not in known_mod_ids and namespace != primary_mod_id and namespace != "minecraft":
                continue
            if is_internal_item_name(raw_name):
                continue
            item_id = f"{namespace}:{raw_name}"
            owner_mod_id = namespace if namespace in known_mod_ids else (source_mods[0].mod_id if len(source_mods) == 1 else namespace)
            entries[item_id] = ItemEntry(
                item_id=item_id,
                display_name=normalize_display_name(item_id, str(value)),
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
        lowered = lowered_keys(raw)
        count_value = lowered.get("count", 1)
        chance_value = lowered.get("chance")
        if "item" in lowered:
            item_value = lowered["item"]
            if isinstance(item_value, str):
                stack = {"item": item_value.lower(), "count": int(count_value)}
                if chance_value is not None:
                    stack["chance"] = chance_value
                return stack
            nested = normalize_item_stack(item_value)
            if nested:
                nested["count"] = int(count_value or nested.get("count", 1))
                if chance_value is not None:
                    nested["chance"] = chance_value
                return nested
        if "id" in lowered:
            id_value = lowered["id"]
            if isinstance(id_value, str):
                stack = {"item": id_value.lower(), "count": int(count_value)}
                if chance_value is not None:
                    stack["chance"] = chance_value
                return stack
            nested = normalize_item_stack(id_value)
            if nested:
                nested["count"] = int(count_value or nested.get("count", 1))
                if chance_value is not None:
                    nested["chance"] = chance_value
                return nested
        if "result" in lowered:
            return normalize_item_stack(lowered["result"])
        if "basepredicate" in lowered:
            return normalize_item_stack(lowered["basepredicate"])
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
        lowered = lowered_keys(raw)
        if "item" in lowered and isinstance(lowered["item"], str):
            return lowered["item"].lower()
        if "tag" in lowered and isinstance(lowered["tag"], str):
            return f"#{lowered['tag'].lower()}"
        if "ingredients" in lowered:
            return normalize_ingredient(lowered["ingredients"])
        if "items" in lowered:
            return normalize_ingredient(lowered["items"])
        if "ingredient" in lowered:
            return normalize_ingredient(lowered["ingredient"])
    return str(raw)


def ingredient_list_from_recipe(recipe: Recipe) -> list[str]:
    values: list[str] = []
    if recipe.ingredients:
        values.extend(normalize_ingredient(value) for value in recipe.ingredients)
    for key in ("ingredient", "base", "addition", "template"):
        if key in recipe.extra:
            values.append(normalize_ingredient(recipe.extra[key]))
    return [value for value in values if value]


def ingredient_item_ids_from_raw(raw: Any) -> list[str]:
    values: list[str] = []
    if raw is None:
        return values
    if isinstance(raw, list):
        for item in raw:
            values.extend(ingredient_item_ids_from_raw(item))
        return values
    if isinstance(raw, dict):
        lowered = lowered_keys(raw)
        if "item" in lowered and isinstance(lowered["item"], str):
            values.append(lowered["item"].lower())
        elif "ingredients" in lowered:
            values.extend(ingredient_item_ids_from_raw(lowered["ingredients"]))
        elif "items" in lowered:
            values.extend(ingredient_item_ids_from_raw(lowered["items"]))
        elif "ingredient" in lowered:
            values.extend(ingredient_item_ids_from_raw(lowered["ingredient"]))
        return values
    return values


def ingredient_item_ids_from_recipe(recipe: Recipe) -> list[str]:
    values: list[str] = []
    for raw in recipe.ingredients:
        values.extend(ingredient_item_ids_from_raw(raw))
    for key in ("ingredient", "base", "addition", "template"):
        if key in recipe.extra:
            values.extend(ingredient_item_ids_from_raw(recipe.extra[key]))
    return list(dict.fromkeys(value for value in values if value))


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

    for key in (
        "category",
        "experience",
        "cookingtime",
        "processingTime",
        "processing_time",
        "heatRequirement",
        "keep_held_item",
        "base",
        "addition",
        "template",
        "neoforge:conditions",
    ):
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


def parse_tag_files(zf: zipfile.ZipFile) -> dict[str, set[str]]:
    tags: dict[str, set[str]] = {}
    for name in zf.namelist():
        if not name.startswith("data/") or not name.endswith(".json"):
            continue
        if "/tags/item/" not in name and "/tags/items/" not in name and "/tags/block/" not in name and "/tags/blocks/" not in name:
            continue
        data = read_json_from_zip(zf, name)
        if not isinstance(data, dict):
            continue
        parts = Path(name).parts
        try:
            namespace = parts[1]
            tag_folder_index = next(i for i, part in enumerate(parts) if part == "tags")
            kind = parts[tag_folder_index + 1]
            tag_path = "/".join(parts[tag_folder_index + 2:]).removesuffix(".json")
        except Exception:
            continue
        tag_id = f"{namespace}:{tag_path}"
        values = set()
        for value in data.get("values", []):
            if isinstance(value, str):
                values.add(value)
            elif isinstance(value, dict) and isinstance(value.get("id"), str):
                values.add(value["id"])
        tags[tag_id] = values
    return tags


def resolve_tag_index(tag_index: dict[str, set[str]]) -> dict[str, set[str]]:
    resolved: dict[str, set[str]] = {}

    def resolve(tag_id: str, seen: set[str] | None = None) -> set[str]:
        if tag_id in resolved:
            return resolved[tag_id]
        seen = seen or set()
        if tag_id in seen:
            return set()
        seen.add(tag_id)
        results: set[str] = set()
        for value in tag_index.get(tag_id, set()):
            if value.startswith("#"):
                results.update(resolve(value[1:], seen.copy()))
            elif ":" in value:
                results.add(value)
        resolved[tag_id] = results
        return results

    for tag_id in tag_index:
        resolve(tag_id)
    return resolved


def heuristic_tag_items(tag_id: str, items: dict[str, ItemEntry]) -> set[str]:
    namespace, _, path = tag_id.partition(":")
    if namespace not in {"c", "forge", "minecraft"}:
        return set()

    parts = [part for part in path.split("/") if part]
    if not parts:
        return set()

    category = parts[0]
    material_parts = parts[1:]
    singular_map = {
        "ingots": ["ingot"],
        "nuggets": ["nugget"],
        "dusts": ["dust"],
        "gems": ["gem"],
        "plates": ["plate"],
        "rods": ["rod"],
        "gears": ["gear"],
        "ores": ["ore"],
        "storage_blocks": ["block"],
        "raw_materials": ["raw"],
        "strings": ["string"],
        "ropes": ["rope"],
        "planks": ["planks"],
        "logs": ["log"],
        "wools": ["wool"],
    }
    wanted_tokens = singular_map.get(category, [category.rstrip("s")])
    wanted_tokens.extend(material_parts)
    wanted_tokens = [token.replace("-", "_").lower() for token in wanted_tokens if token]

    matches: set[str] = set()
    for item_id, item in items.items():
        item_path = item_id.partition(":")[2].lower()
        if all(token in item_path for token in wanted_tokens):
            matches.add(item_id)
    return matches


def ensure_referenced_items_exist(items: dict[str, ItemEntry], recipes: list[Recipe], known_mod_ids: set[str]) -> None:
    for recipe in recipes:
        referenced_ids = ingredient_item_ids_from_recipe(recipe) + [
            str(output.get("item", "")) for output in recipe.outputs if isinstance(output.get("item", ""), str)
        ]
        for item_id in referenced_ids:
            if not item_id or item_id.startswith("#") or item_id in items or ":" not in item_id:
                continue
            namespace, _, path = item_id.partition(":")
            owner_mod_id = namespace if namespace in known_mod_ids else namespace
            items[item_id] = ItemEntry(
                item_id=item_id,
                display_name=fallback_display_name(item_id),
                entry_type="item",
                namespace=namespace,
                owner_mod_id=owner_mod_id,
                source_jar=f"{recipe.mod_id}.jar",
            )


def load_catalog() -> tuple[list[Path], Path | None, dict[str, ModEntry], dict[str, ItemEntry]]:
    index_data = load_pack_index()
    minecraft_version = pack_minecraft_version(index_data)
    download_missing_mod_jars(index_data)
    jar_paths = find_jar_paths(index_data)
    minecraft_client_jar = ensure_minecraft_client_jar(minecraft_version)
    jar_project_ids: dict[str, str] = {}
    for file_entry in index_data.get("files", []):
        path = file_entry.get("path", "")
        if not path.startswith("mods/"):
            continue
        jar_project_ids[Path(path).name] = parse_modrinth_project_id((file_entry.get("downloads") or [""])[0])
    project_meta = load_modrinth_projects(sorted({value for value in jar_project_ids.values() if value}))

    mods: dict[str, ModEntry] = {}
    items: dict[str, ItemEntry] = {}
    all_recipes: list[Recipe] = []
    tag_index: dict[str, set[str]] = {}

    for jar_path in jar_paths:
        with zipfile.ZipFile(jar_path) as zf:
            source_mods = parse_mod_metadata(zf, jar_path.name)
            parsed_tags = parse_tag_files(zf)
            for tag_id, values in parsed_tags.items():
                tag_index.setdefault(tag_id, set()).update(values)
            for mod in source_mods:
                project_id = jar_project_ids.get(jar_path.name, "")
                if project_id and project_id in project_meta:
                    project = project_meta[project_id]
                    mod.modrinth_project_id = project_id
                    mod.modrinth_slug = project.get("slug", "") or ""
                    if mod.modrinth_slug:
                        mod.modrinth_url = f"https://modrinth.com/mod/{mod.modrinth_slug}"
                    mod.modrinth_icon_url = project.get("icon_url", "") or ""
                    mod.project_summary = project.get("description", "") or ""
                    mod.project_body = strip_markdown(project.get("body", "") or "")
                    mod.categories = list(project.get("categories", []) or [])
                    mod.client_side = project.get("client_side", "") or ""
                    mod.server_side = project.get("server_side", "") or ""
                    mod.downloads = int(project.get("downloads", 0) or 0)
                    mod.issues_url = project.get("issues_url", "") or ""
                    mod.source_url = project.get("source_url", "") or ""
                    mod.wiki_url = project.get("wiki_url", "") or ""
                    mod.discord_url = project.get("discord_url", "") or ""
                mods.setdefault(mod.mod_id, mod)

            for item in parse_item_language_entries(zf, source_mods, jar_path.name):
                current = items.get(item.item_id)
                if current is None or len(current.display_name) < len(item.display_name):
                    items[item.item_id] = item

            primary_mod_id = source_mods[0].mod_id
            for recipe in parse_recipes(zf, primary_mod_id):
                all_recipes.append(recipe)
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

    ensure_referenced_items_exist(items, all_recipes, set(mods))

    items = {
        item_id: item
        for item_id, item in items.items()
        if (item.namespace in mods or item.namespace == "minecraft")
        and not (is_internal_item_name(item.item_id.partition(":")[2]) and len(item.recipes) == 0)
    }

    resolved_tags = resolve_tag_index(tag_index)

    for recipe in all_recipes:
        for ingredient_id in ingredient_item_ids_from_recipe(recipe):
            if ingredient_id in items:
                items[ingredient_id].usages.append(recipe)
        for ingredient in ingredient_list_from_recipe(recipe):
            if not ingredient.startswith("#"):
                continue
            tag_id = ingredient[1:]
            matching_items = resolved_tags.get(tag_id, set()) or heuristic_tag_items(tag_id, items)
            for item_id in matching_items:
                if item_id in items:
                    items[item_id].usages.append(recipe)

    for item in items.values():
        seen_recipe_ids: set[str] = set()
        deduped_recipes: list[Recipe] = []
        for recipe in item.recipes:
            if recipe.recipe_id in seen_recipe_ids:
                continue
            seen_recipe_ids.add(recipe.recipe_id)
            deduped_recipes.append(recipe)
        item.recipes = deduped_recipes

        seen_usage_ids: set[str] = set()
        deduped_usages: list[Recipe] = []
        for recipe in item.usages:
            if recipe.recipe_id in seen_usage_ids:
                continue
            seen_usage_ids.add(recipe.recipe_id)
            deduped_usages.append(recipe)
        item.usages = deduped_usages

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

    return jar_paths, minecraft_client_jar, dict(sorted(mods.items())), dict(sorted(items.items()))


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


def candidate_model_names(item_id: str) -> list[str]:
    namespace, _, path = item_id.partition(":")
    if not namespace or not path:
        return []
    return [
        f"assets/{namespace}/items/{path}.json",
        f"assets/{namespace}/models/item/{path}.json",
        f"assets/{namespace}/models/block/{path}.json",
    ]


def model_ref_to_path(model_ref: str) -> str:
    namespace, _, path = model_ref.partition(":")
    namespace = namespace or "minecraft"
    return f"assets/{namespace}/models/{path}.json"


def texture_ref_to_path(texture_ref: str) -> str:
    namespace, _, path = texture_ref.partition(":")
    namespace = namespace or "minecraft"
    return f"assets/{namespace}/textures/{path}.png"


def extract_texture_from_model(
    zf: zipfile.ZipFile,
    model_ref: str,
    names: set[str],
    visited: set[str] | None = None,
) -> str:
    visited = visited or set()
    model_path = model_ref_to_path(model_ref)
    if model_path in visited or model_path not in names:
        return ""
    visited.add(model_path)
    model_data = read_json_from_zip(zf, model_path)
    if not isinstance(model_data, dict):
        return ""

    textures = model_data.get("textures", {}) if isinstance(model_data.get("textures"), dict) else {}
    for key in ("layer0", "all", "top", "side", "front", "particle"):
        value = textures.get(key)
        if isinstance(value, str):
            if value.startswith("#"):
                alias = textures.get(value[1:])
                if isinstance(alias, str):
                    value = alias
                else:
                    continue
            candidate = texture_ref_to_path(value)
            if candidate in names:
                return candidate

    parent = model_data.get("parent")
    if isinstance(parent, str):
        return extract_texture_from_model(zf, parent, names, visited)
    return ""


def resolve_item_texture(zf: zipfile.ZipFile, item_id: str, names: set[str]) -> str:
    for candidate in candidate_texture_names(item_id):
        if candidate in names:
            return candidate

    for model_path in candidate_model_names(item_id):
        if model_path not in names:
            continue
        model_data = read_json_from_zip(zf, model_path)
        if not isinstance(model_data, dict):
            continue
        model_ref = ""
        if model_path.startswith("assets/") and "/items/" in model_path:
            model_field = model_data.get("model")
            if isinstance(model_field, str):
                model_ref = model_field
            elif isinstance(model_field, dict) and isinstance(model_field.get("model"), str):
                model_ref = model_field["model"]
        else:
            namespace = item_id.partition(":")[0] or "minecraft"
            model_ref = f"{namespace}:{model_path.split(f'assets/{namespace}/models/', 1)[1].removesuffix('.json')}"

        if model_ref:
            texture_path = extract_texture_from_model(zf, model_ref, names)
            if texture_path:
                return texture_path
    return ""


def copy_asset_from_jar(zf: zipfile.ZipFile, asset_path: str, target_root: Path) -> str:
    asset_rel = Path(asset_path).relative_to("assets")
    relative = Path("assets") / asset_rel.parts[0] / Path(*asset_rel.parts[1:])
    target = target_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with zf.open(asset_path) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return relative.as_posix()


def extract_gui_assets(minecraft_client_jar: Path | None) -> None:
    if not minecraft_client_jar or not minecraft_client_jar.exists():
        return
    wanted = [
        "assets/minecraft/textures/gui/container/crafting_table.png",
        "assets/minecraft/textures/gui/container/furnace.png",
        "assets/minecraft/textures/gui/container/blast_furnace.png",
        "assets/minecraft/textures/gui/container/stonecutter.png",
        "assets/minecraft/textures/gui/container/smithing.png",
        "assets/minecraft/textures/gui/sprites/container/slot.png",
        "assets/minecraft/textures/gui/sprites/container/furnace/lit_progress.png",
        "assets/minecraft/textures/gui/sprites/container/furnace/burn_progress.png",
        "assets/minecraft/textures/gui/sprites/container/blast_furnace/lit_progress.png",
        "assets/minecraft/textures/gui/sprites/container/blast_furnace/burn_progress.png",
        "assets/minecraft/textures/gui/sprites/container/stonecutter/recipe.png",
        "assets/minecraft/textures/gui/sprites/container/smithing/error.png",
    ]
    with zipfile.ZipFile(minecraft_client_jar) as zf:
        names = set(zf.namelist())
        for asset_path in wanted:
            if asset_path in names:
                copy_asset_from_jar(zf, asset_path, SITE_DIR)
                if asset_path.startswith("assets/minecraft/textures/gui/container/"):
                    try:
                        from PIL import Image

                        rel = copy_asset_from_jar(zf, asset_path, SITE_DIR)
                        full_path = SITE_DIR / rel
                        crop_dir = SITE_DIR / "assets" / "minecraft" / "textures" / "gui" / "cropped"
                        crop_dir.mkdir(parents=True, exist_ok=True)
                        with Image.open(full_path) as image:
                            cropped = image.crop((0, 0, 176, 166))
                            cropped.save(crop_dir / Path(asset_path).name)
                            if Path(asset_path).name == "crafting_table.png":
                                image.crop((26, 15, 150, 73)).save(crop_dir / "crafting_table_panel.png")
                    except Exception:
                        pass


def extract_item_icons(jar_paths: list[Path], items: dict[str, ItemEntry], minecraft_client_jar: Path | None = None) -> None:
    texture_root = SITE_DIR / "assets" / "textures"
    texture_root.mkdir(parents=True, exist_ok=True)

    icon_sources = list(jar_paths)
    if minecraft_client_jar and minecraft_client_jar.exists():
        icon_sources.append(minecraft_client_jar)

    for jar_path in icon_sources:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            for item in items.values():
                if item.icon_path:
                    continue
                texture_path = resolve_item_texture(zf, item.item_id, names)
                if not texture_path:
                    continue
                asset_rel = Path(texture_path).relative_to("assets")
                relative = Path("assets") / "textures" / asset_rel.parts[0] / Path(*asset_rel.parts[2:])
                target = SITE_DIR / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    with zf.open(texture_path) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                item.icon_path = relative.as_posix()


def extract_mod_icons(mods: dict[str, ModEntry]) -> None:
    icon_root = SITE_DIR / "assets" / "mod-icons"
    icon_root.mkdir(parents=True, exist_ok=True)
    for mod in mods.values():
        if not mod.modrinth_icon_url:
            continue
        parsed = urllib.parse.urlparse(mod.modrinth_icon_url)
        suffix = Path(parsed.path).suffix or ".png"
        target = icon_root / f"{slugify(mod.mod_id)}{suffix}"
        if not target.exists() and not download_file(mod.modrinth_icon_url, target):
            continue
        mod.modrinth_icon_path = f"assets/mod-icons/{target.name}"


def item_icon_html(item_id: str, rel_root: str, items: dict[str, ItemEntry], *, large: bool = False) -> str:
    item = items.get(item_id)
    if not item or not item.icon_path:
        return ""
    size_class = " large" if large else ""
    return f'<img class="icon{size_class}" src="{rel_root}/{safe_text(item.icon_path)}" alt="{safe_text(item.display_name)}">'


def item_ref_href(item_id: str, rel_root: str, items: dict[str, ItemEntry]) -> str:
    if item_id.startswith("#") or item_id not in items:
        return ""
    return f"{rel_root}/{item_url(item_id)}"


def mod_icon_html(mod: ModEntry, rel_root: str, *, large: bool = False) -> str:
    if not mod.modrinth_icon_path:
        return ""
    size_class = " large" if large else ""
    return f'<img class="icon{size_class}" src="{rel_root}/{safe_text(mod.modrinth_icon_path)}" alt="{safe_text(mod.name)}">'


def render_slot(label: str, rel_root: str, items: dict[str, ItemEntry], icon_item_id: str = "") -> str:
    if not label:
        return '<div class="slot empty">Empty</div>'
    icon = ""
    item_id = icon_item_id
    if not item_id and re.match(r"^[a-z0-9_.-]+:[a-z0-9_./-]+(?: ×\d+)?$", label):
        item_id = label.split(" ×", 1)[0]
    if item_id and not item_id.startswith("#"):
        icon = item_icon_html(item_id, rel_root, items)
    inner = f"{icon}<div>{safe_text(label)}</div>"
    href = item_ref_href(item_id, rel_root, items) if item_id else ""
    if href:
        inner = f'<a class="slot-link slot-content" href="{safe_text(href)}">{inner}</a>'
    else:
        inner = f'<div class="slot-content">{inner}</div>'
    return f'<div class="slot">{inner}</div>'


def render_stack_label(stack: dict[str, Any]) -> str:
    item_id = stack.get("item", "")
    count = int(stack.get("count", 1))
    label = f"{item_id} ×{count}" if count > 1 else str(item_id)
    if "chance" in stack:
        try:
            label += f" ({float(stack['chance'])*100:.0f}%)"
        except Exception:
            pass
    return label


def render_stack_list(stacks: list[dict[str, Any]], rel_root: str, items: dict[str, ItemEntry]) -> str:
    if not stacks:
        return "<div class='muted'>None</div>"
    return "<div class='wiki-stack-list'>" + "".join(
        render_wiki_stack(stack, rel_root, items) for stack in stacks
    ) + "</div>"


def render_single_stack(stack: dict[str, Any] | None, rel_root: str, items: dict[str, ItemEntry]) -> str:
    if not stack:
        return render_wiki_slot("", "", rel_root, items)
    return render_wiki_stack(stack, rel_root, items)


def render_gui_slot(
    item_id: str,
    label: str,
    rel_root: str,
    items: dict[str, ItemEntry],
    *,
    extra_badge: str = "",
    extra_class: str = "",
) -> str:
    classes = "gui-slot"
    if extra_class:
        classes += f" {extra_class}"
    href = item_ref_href(item_id, rel_root, items) if item_id else ""
    icon = item_icon_html(item_id, rel_root, items) if item_id and not item_id.startswith("#") else ""
    fallback = ""
    if not icon:
        short = label[:10] if label else "?"
        fallback = f"<span class='gui-fallback'>{safe_text(short)}</span>"
    count_badge = ""
    match = re.search(r"[×Ã—](\d+)", label)
    if match:
        count_badge = f"<span class='gui-count'>{safe_text(match.group(1))}</span>"
    chance_badge = f"<span class='gui-chance'>{safe_text(extra_badge)}</span>" if extra_badge else ""
    inner = f"{icon}{fallback}{count_badge}{chance_badge}"
    title_attr = safe_text(label)
    if href:
        return f'<a class="{classes}" href="{safe_text(href)}" title="{title_attr}">{inner}</a>'
    return f'<div class="{classes}" title="{title_attr}">{inner}</div>'


def render_gui_stack(
    stack: dict[str, Any] | None,
    rel_root: str,
    items: dict[str, ItemEntry],
    *,
    extra_class: str = "",
) -> str:
    if not stack:
        return f'<div class="gui-slot empty {safe_text(extra_class)}"></div>'
    label = friendly_stack_label(stack, items)
    badge = ""
    if "chance" in stack:
        try:
            badge = f"{float(stack['chance']) * 100:.0f}%"
        except Exception:
            badge = ""
    return render_gui_slot(str(stack.get("item", "")), label, rel_root, items, extra_badge=badge, extra_class=extra_class)


def render_wiki_slot(
    item_id: str,
    label: str,
    rel_root: str,
    items: dict[str, ItemEntry],
    *,
    count: int = 1,
    extra_badge: str = "",
    extra_class: str = "",
) -> str:
    classes = "wiki-slot"
    if extra_class:
        classes += f" {extra_class}"
    title_attr = safe_text(label or item_id or "Empty")
    if not item_id:
        return f'<div class="{classes} empty" title="{title_attr}"></div>'
    href = item_ref_href(item_id, rel_root, items) if item_id and not item_id.startswith("#") else ""
    icon = item_icon_html(item_id, rel_root, items) if item_id and not item_id.startswith("#") else ""
    fallback = ""
    if not icon:
        short = (label or item_id or "?")[:10]
        fallback = f"<span class='wiki-slot-fallback'>{safe_text(short)}</span>"
    count_badge = f"<span class='wiki-slot-count'>{count}</span>" if count > 1 else ""
    chance_badge = f"<span class='wiki-slot-chance'>{safe_text(extra_badge)}</span>" if extra_badge else ""
    inner = f"<span class='wiki-slot-inner'>{icon}{fallback}{count_badge}{chance_badge}</span>"
    if href:
        return f'<a class="{classes}" href="{safe_text(href)}" title="{title_attr}">{inner}</a>'
    return f'<div class="{classes}" title="{title_attr}">{inner}</div>'


def render_wiki_ingredient(value: str, rel_root: str, items: dict[str, ItemEntry], *, extra_class: str = "") -> str:
    if not value:
        return render_wiki_slot("", "", rel_root, items, extra_class=extra_class)
    return render_wiki_slot(
        value,
        friendly_ingredient_label(value, items),
        rel_root,
        items,
        extra_class=extra_class,
    )


def render_wiki_stack(
    stack: dict[str, Any] | None,
    rel_root: str,
    items: dict[str, ItemEntry],
    *,
    extra_class: str = "",
) -> str:
    if not stack:
        return render_wiki_slot("", "", rel_root, items, extra_class=extra_class)
    badge = ""
    if "chance" in stack:
        try:
            badge = f"{float(stack['chance']) * 100:.0f}%"
        except Exception:
            badge = ""
    return render_wiki_slot(
        str(stack.get("item", "")),
        friendly_stack_label(stack, items),
        rel_root,
        items,
        count=int(stack.get("count", 1)),
        extra_badge=badge,
        extra_class=extra_class,
    )


def render_gui_canvas(rel_root: str, asset_path: str, class_name: str) -> str:
    asset_file = SITE_DIR / asset_path.replace("/", os.sep)
    if asset_file.exists():
        mime = "image/png" if asset_file.suffix.lower() == ".png" else "image/webp"
        encoded = base64.b64encode(asset_file.read_bytes()).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        return f'<img class="gui-bg {safe_text(class_name)}" src="{data_url}" alt="">'
    return f'<img class="gui-bg {safe_text(class_name)}" src="{rel_root}/{safe_text(asset_path)}" alt="">'


def render_vanilla_gui(
    rel_root: str,
    asset_path: str,
    wrapper_class: str,
    bg_class: str,
    slots_html: str,
    *,
    scale: float,
) -> str:
    return (
        f"<div class='mc-gui {safe_text(wrapper_class)}' style='--gui-scale:{scale};'>"
        f"{render_gui_canvas(rel_root, asset_path, bg_class)}"
        f"{slots_html}"
        f"</div>"
    )


def recipe_asset_rel(name: str) -> str:
    return f"assets/recipes/{name}"


def recipe_asset_path(name: str) -> Path:
    return SITE_DIR / "assets" / "recipes" / name


def render_recipe_image(
    image_rel: str,
    rel_root: str,
    *,
    alt: str,
    width: int,
    height: int,
    scale: float,
    hotspots: list[dict[str, Any]] | None = None,
) -> str:
    hotspots = hotspots or []
    overlay_html = []
    scaled_width = width * scale
    scaled_height = height * scale
    for hotspot in hotspots:
        item_id = str(hotspot.get("item_id", ""))
        if not item_id:
            continue
        href = f"{rel_root}/{item_url(item_id)}"
        x = float(hotspot["x"]) * scale
        y = float(hotspot["y"]) * scale
        size = float(hotspot.get("size", 18)) * scale
        label = hotspot.get("label", item_id)
        overlay_html.append(
            f"<a class='recipe-hotspot' href='{safe_text(href)}' title='{safe_text(label)}' "
            f"style='left:{x}px;top:{y}px;width:{size}px;height:{size}px;'></a>"
        )
    return (
        f"<div class='recipe-render' style='width:{scaled_width}px;height:{scaled_height}px;'>"
        f"<img class='recipe-render-img' src='{rel_root}/{safe_text(image_rel)}' alt='{safe_text(alt)}'>"
        f"{''.join(overlay_html)}"
        f"</div>"
    )


def load_slot_icon(item_id: str, items: dict[str, ItemEntry]) -> Any | None:
    try:
        from PIL import Image
    except Exception:
        return None
    item = items.get(item_id)
    if not item or not item.icon_path:
        return None
    path = SITE_DIR / item.icon_path.replace("/", os.sep)
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def compose_recipe_image(
    recipe: Recipe,
    items: dict[str, ItemEntry],
    *,
    layout: str,
    ingredients: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
) -> str:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return ""

    backgrounds = {
        "crafting": SITE_DIR / "assets" / "minecraft" / "textures" / "gui" / "cropped" / "crafting_table.png",
        "furnace": SITE_DIR / "assets" / "minecraft" / "textures" / "gui" / "cropped" / "furnace.png",
        "blast": SITE_DIR / "assets" / "minecraft" / "textures" / "gui" / "cropped" / "blast_furnace.png",
        "stonecutter": SITE_DIR / "assets" / "minecraft" / "textures" / "gui" / "cropped" / "stonecutter.png",
        "smithing": SITE_DIR / "assets" / "minecraft" / "textures" / "gui" / "cropped" / "smithing.png",
    }
    base_path = backgrounds.get(layout)
    if not base_path or not base_path.exists():
        return ""

    base = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(base)
    slot_positions = {
        "crafting": [(30, 17), (48, 17), (66, 17), (30, 35), (48, 35), (66, 35), (30, 53), (48, 53), (66, 53)],
        "furnace": [(56, 17)],
        "blast": [(56, 17)],
        "stonecutter": [(20, 33)],
        "smithing": [(8, 48), (26, 48), (44, 48)],
    }
    output_positions = {
        "crafting": [(124, 35)],
        "furnace": [(116, 35)],
        "blast": [(116, 35)],
        "stonecutter": [(143, 33)],
        "smithing": [(98, 48)],
    }

    def paste_stack(stack: dict[str, Any] | None, xy: tuple[int, int]) -> None:
        if not stack:
            return
        item_id = str(stack.get("item", ""))
        icon = load_slot_icon(item_id, items) if item_id and not item_id.startswith("#") else None
        x, y = xy
        if icon:
            icon = icon.resize((16, 16))
            base.alpha_composite(icon, (x + 1, y + 1))
        else:
            label = friendly_stack_label(stack, items)
            short = label[:6]
            draw.text((x + 1, y + 5), short, fill=(255, 255, 255, 255))

    for stack, pos in zip(ingredients, slot_positions.get(layout, [])):
        paste_stack(stack, pos)
    for stack, pos in zip(outputs, output_positions.get(layout, [])):
        paste_stack(stack, pos)

    if layout == "crafting":
        # Show only the crafting interface region: 3x3 grid, arrow, and result.
        base = base.crop((26, 15, 150, 73))

    target_name = f"{slugify(recipe.recipe_id)}-{layout}.png"
    target = recipe_asset_path(target_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    base.save(target)
    return recipe_asset_rel(target_name)


def hotspot(item_id: str | None, x: int, y: int, label: str, *, size: int = 18) -> dict[str, Any] | None:
    if not item_id or item_id.startswith("#"):
        return None
    return {"item_id": item_id, "x": x, "y": y, "size": size, "label": label}


def workstation_shell(station: str, layout_class: str, inner_html: str, recipe_id: str, recipe_type: str) -> str:
    frame_class = f"frame-{slugify(layout_class)}"
    return f"""
    <div class="recipe-card workstation">
      <div class="workstation-badge">{safe_text(station)}</div>
      <div class="recipe-header">
        <strong>{safe_text(recipe_type)}</strong>
        <span class="muted path">{safe_text(recipe_id)}</span>
      </div>
      <div class="workstation-frame {safe_text(frame_class)}">
        <div class="crafting-layout {safe_text(layout_class)}">
          {inner_html}
        </div>
      </div>
    </div>
    """


def render_recipe_meta(meta_parts: list[str]) -> str:
    if not meta_parts:
        return ""
    chips = "".join(f"<span class='mc-meta-chip'>{safe_text(part)}</span>" for part in meta_parts)
    return f"<div class='recipe-meta mc-meta-row'>{chips}</div>"


def render_process_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry], title: str) -> str:
    ingredient_stacks = []
    for value in ingredient_list_from_recipe(recipe):
        ingredient_stacks.append({"item": value, "count": 1})
    meta_parts = []
    for key in ("processing_time", "processingTime", "cookingtime", "experience", "heatRequirement"):
        if key in recipe.extra:
            meta_parts.append(f"{key}: {recipe.extra[key]}")
    main_input = ingredient_stacks[0] if ingredient_stacks else None
    main_output = recipe.outputs[0] if recipe.outputs else None
    extra_outputs = recipe.outputs[1:] if len(recipe.outputs) > 1 else []

    layout_class = "furnace-ui"
    station = title
    if recipe.recipe_type == "minecraft:stonecutting":
        layout_class = "stonecutter-ui"
        station = "Stonecutter"
        inner = (
            render_vanilla_gui(
                rel_root,
                "assets/minecraft/textures/gui/cropped/stonecutter.png",
                "mc-stonecutter",
                "mc-stonecutter-canvas",
                (
                    render_gui_stack(main_input, rel_root, items, extra_class="stonecut-input")
                    + render_gui_stack(main_output, rel_root, items, extra_class="stonecut-output")
                ),
                scale=2.35,
            )
            + f"{render_recipe_meta(meta_parts)}"
        )
        return workstation_shell(station, layout_class, inner, recipe.recipe_id, title)
    elif recipe.recipe_type.startswith("create:"):
        layout_class = "create-ui"
        station = title
        inner = (
            "<div class='jsran-widget jsran-widget-create'>"
            "<div class='create-screen'>"
            f"<div class='result-stack'>{render_stack_list(ingredient_stacks, rel_root, items)}</div>"
            "<div class='create-center'><div class='create-cog' aria-hidden='true'></div><div class='progress-bar'></div></div>"
            f"<div class='result-stack'>{render_stack_list(recipe.outputs, rel_root, items)}</div>"
            "</div>"
            "</div>"
            f"{render_recipe_meta(meta_parts)}"
        )
        return workstation_shell(station, layout_class, inner, recipe.recipe_id, title)

    inner = (
        render_vanilla_gui(
            rel_root,
            "assets/minecraft/textures/gui/cropped/blast_furnace.png" if recipe.recipe_type == "minecraft:blasting" else "assets/minecraft/textures/gui/cropped/furnace.png",
            "mc-furnace",
            "mc-furnace-canvas",
            (
                render_gui_stack(main_input, rel_root, items, extra_class="furnace-input-slot")
                + "<div class='gui-slot empty furnace-fuel-slot'></div>"
                + render_gui_stack(main_output, rel_root, items, extra_class="furnace-output-slot")
            ),
            scale=2.2,
        )
        + (f"<div class='byproduct-row'><div class='ui-subtitle'>Extra Outputs</div>{render_stack_list(extra_outputs, rel_root, items)}</div>" if extra_outputs else "")
        + render_recipe_meta(meta_parts)
    )
    return workstation_shell(station, layout_class, inner, recipe.recipe_id, title)


def render_smithing_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry], title: str) -> str:
    template = recipe.extra.get("template")
    base = recipe.extra.get("base")
    addition = recipe.extra.get("addition")
    output = recipe.outputs[0] if recipe.outputs else None
    inner = (
        render_vanilla_gui(
            rel_root,
            "assets/minecraft/textures/gui/cropped/smithing.png",
            "mc-smithing",
            "mc-smithing-canvas",
            (
                render_gui_slot(normalize_ingredient(template) if template else "", friendly_ingredient_label(normalize_ingredient(template), items) if template else "", rel_root, items, extra_class="smith-template")
                + render_gui_slot(normalize_ingredient(base) if base else "", friendly_ingredient_label(normalize_ingredient(base), items) if base else "", rel_root, items, extra_class="smith-base")
                + render_gui_slot(normalize_ingredient(addition) if addition else "", friendly_ingredient_label(normalize_ingredient(addition), items) if addition else "", rel_root, items, extra_class="smith-addition")
                + render_gui_stack(output, rel_root, items, extra_class="smith-output")
            ),
            scale=2.2,
        )
    )
    return workstation_shell("Smithing Table", "smithing-ui", inner, recipe.recipe_id, title)


def render_crafting_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry]) -> str:
    pattern = list(recipe.pattern or [])
    while len(pattern) < 3:
        pattern.append("")

    rows = []
    for row in pattern[:3]:
        for char in row.ljust(3)[:3]:
            rows.append("" if char == " " else normalize_ingredient(recipe.key.get(char)))

    output = recipe.outputs[0] if recipe.outputs else {"item": "unknown", "count": 1}
    slots = []
    for idx, value in enumerate(rows):
        item_id = value if value else ""
        slots.append(
            render_gui_slot(
                item_id,
                friendly_ingredient_label(value, items) if value else "",
                rel_root,
                items,
                extra_class=f"craft-panel-slot-{idx}",
            )
            if value
            else f"<div class='gui-slot empty craft-panel-slot-{idx}'></div>"
        )
    slots.append(render_gui_stack(output, rel_root, items, extra_class="craft-panel-result"))
    inner = render_vanilla_gui(
        rel_root,
        "assets/minecraft/textures/gui/cropped/crafting_table_panel.png",
        "mc-crafting-panel",
        "mc-crafting-panel-canvas",
        "".join(slots),
        scale=4.2,
    )
    return workstation_shell("Crafting Table", "crafting-table", inner, recipe.recipe_id, recipe.recipe_type)


def render_shapeless_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry]) -> str:
    ingredients = [normalize_ingredient(value) for value in recipe.ingredients][:9]
    while len(ingredients) < 9:
        ingredients.append("")
    output = recipe.outputs[0] if recipe.outputs else {"item": "unknown", "count": 1}
    slots = []
    for idx, value in enumerate(ingredients):
        item_id = value if value else ""
        slots.append(
            render_gui_slot(
                item_id,
                friendly_ingredient_label(value, items) if value else "",
                rel_root,
                items,
                extra_class=f"craft-panel-slot-{idx}",
            )
            if value
            else f"<div class='gui-slot empty craft-panel-slot-{idx}'></div>"
        )
    slots.append(render_gui_stack(output, rel_root, items, extra_class="craft-panel-result"))
    inner = (
        render_vanilla_gui(
            rel_root,
            "assets/minecraft/textures/gui/cropped/crafting_table_panel.png",
            "mc-crafting-panel",
            "mc-crafting-panel-canvas",
            "".join(slots),
            scale=4.2,
        )
        + "<div class='recipe-meta mc-meta-row'><span class='mc-meta-chip'>Shapeless</span></div>"
    )
    return workstation_shell("Crafting Table", "crafting-table", inner, recipe.recipe_id, recipe.recipe_type)


def render_generic_recipe(recipe: Recipe) -> str:
    outputs = ", ".join(render_stack_label(output) for output in recipe.outputs) or "Unknown"
    ingredients = [normalize_ingredient(value) for value in recipe.ingredients]
    ingredient_html = "".join(f'<span class="chip">{safe_text(value)}</span>' for value in ingredients if value)
    extra = ", ".join(f"{key}={value}" for key, value in recipe.extra.items())
    return f"""
    <div class="recipe-card workstation">
      <div class="workstation-badge">Recipe</div>
      <div class="recipe-header">
        <strong>{safe_text(recipe.recipe_type)}</strong>
        <span class="muted path">{safe_text(recipe.recipe_id)}</span>
      </div>
      <div class="workstation-frame frame-create-ui">
        <div class="crafting-layout create-ui">
          <div class="jsran-widget jsran-widget-generic">
            <div class="wiki-generic">
              <div class="wiki-generic-section">
                <div class="ui-title left">Ingredients</div>
                <div class="ingredient-list">{ingredient_html or "<span class='muted'>No ingredient data parsed.</span>"}</div>
              </div>
              <div class="wiki-arrow wiki-arrow-wide" aria-hidden="true"></div>
              <div class="wiki-generic-section">
                <div class="ui-title right">Outputs</div>
                <div class="generic-output">{safe_text(outputs)}</div>
              </div>
            </div>
          </div>
          <div class="recipe-meta">{safe_text(extra)}</div>
        </div>
      </div>
    </div>
    """


def render_recipe(recipe: Recipe, rel_root: str, items: dict[str, ItemEntry]) -> str:
    if recipe.recipe_type in {"minecraft:smelting", "minecraft:blasting", "minecraft:smoking", "minecraft:campfire_cooking"}:
        return render_process_recipe(recipe, rel_root, items, recipe.recipe_type.split(":")[1].replace("_", " ").title())
    if recipe.recipe_type == "minecraft:stonecutting":
        return render_process_recipe(recipe, rel_root, items, "Stonecutting")
    if recipe.recipe_type in {"minecraft:smithing_transform", "minecraft:smithing_trim"}:
        return render_smithing_recipe(recipe, rel_root, items, recipe.recipe_type.split(":")[1].replace("_", " ").title())
    if recipe.recipe_type.startswith("create:"):
        return render_process_recipe(recipe, rel_root, items, recipe.recipe_type.split(":", 1)[1].replace("_", " ").title())
    if recipe.pattern:
        return render_crafting_recipe(recipe, rel_root, items)
    if "crafting_shapeless" in recipe.recipe_type:
        return render_shapeless_recipe(recipe, rel_root, items)
    return render_generic_recipe(recipe)


def build_home(mods: dict[str, ModEntry], items: dict[str, ItemEntry]) -> None:
    featured = [
        "minecolonies",
        "create",
        "irons_spellbooks",
        "bettercombat",
        "endrem",
        "simple_voice_chat",
    ]
    featured_links = "".join(
        f"<a class='inline-flex items-center rounded-full border border-sky-400/20 bg-sky-400/10 px-3 py-1.5 text-sm font-medium text-sky-100 transition hover:border-sky-300/40 hover:bg-sky-400/20' href='{safe_text(mod_url(mod_id))}'>{safe_text(mods[mod_id].name)}</a>"
        for mod_id in featured
        if mod_id in mods
    )
    body = f"""
    <section class="relative overflow-hidden rounded-[32px] border border-slate-700/60 bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800 px-8 py-10 shadow-2xl shadow-slate-950/40">
      <div class="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(56,189,248,0.18),transparent_28%),radial-gradient(circle_at_bottom_left,rgba(249,115,22,0.14),transparent_24%)]"></div>
      <div class="relative">
        <div class="mb-3 inline-flex items-center rounded-full border border-amber-400/20 bg-amber-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.24em] text-amber-200">Pack Wiki</div>
        <div class="max-w-3xl">
          <h1 class="text-4xl font-black tracking-tight text-white sm:text-5xl">JombiePack Wiki</h1>
          <p class="mt-4 text-lg leading-8 text-slate-300">JombiePack is a NeoForge 1.21.1 pack built around co-op survival, large-scale exploration, active combat, colony building, Create machinery, and a stronger sense of atmosphere and progression.</p>
        </div>
        <div class="mt-8 grid gap-4 sm:grid-cols-3">
          <div class="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-5 backdrop-blur">
            <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Mods</div>
            <div class="mt-2 text-3xl font-black text-white">{len(mods)}</div>
          </div>
          <div class="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-5 backdrop-blur">
            <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Catalog Entries</div>
            <div class="mt-2 text-3xl font-black text-white">{len(items)}</div>
          </div>
          <div class="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-5 backdrop-blur">
            <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Best For</div>
            <div class="mt-2 text-lg font-semibold text-white">Exploration, tech, combat</div>
          </div>
        </div>
      </div>
    </section>

    <section class="mt-8 rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
      <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div class="max-w-2xl">
          <h2 class="text-2xl font-bold text-white">Search the Wiki</h2>
          <p class="mt-2 text-sm leading-6 text-slate-400">Search mods, item names, blocks, and registry IDs from anywhere in the pack.</p>
        </div>
      </div>
      <div class="mt-5">
        <input id="search" class="searchbox" placeholder="Search mods, items, or registry ids">
      </div>
      <div id="results" class="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3"></div>
    </section>

    <section class="mt-8 grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
      <div class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
        <h2 class="text-2xl font-bold text-white">Pack Focus</h2>
        <p class="mt-3 max-w-3xl text-sm leading-7 text-slate-300">Expect upgraded structures, more dangerous roaming, spell and weapon build variety, long-term settlement play through MineColonies, and a slower End progression path through End Remastered. This wiki is designed to help players jump from broad pack systems into exact items and recipes quickly.</p>
        <div class="mt-5 flex flex-wrap gap-3">{featured_links}</div>
      </div>
      <div class="space-y-6">
        <div class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
          <h2 class="text-xl font-bold text-white">Browse</h2>
          <div class="mt-4 grid gap-3">
            <a class="rounded-2xl border border-slate-700/50 bg-slate-800/70 px-4 py-4 text-slate-100 transition hover:border-sky-400/30 hover:bg-slate-800" href="mods/index.html">
              <div class="text-sm font-semibold">All Mods</div>
              <div class="mt-1 text-sm text-slate-400">Project pages, docs, links, and pack presence</div>
            </a>
            <a class="rounded-2xl border border-slate-700/50 bg-slate-800/70 px-4 py-4 text-slate-100 transition hover:border-sky-400/30 hover:bg-slate-800" href="items/index.html">
              <div class="text-sm font-semibold">All Items and Blocks</div>
              <div class="mt-1 text-sm text-slate-400">Recipe browser, usage lookup, and per-item pages</div>
            </a>
          </div>
        </div>
        <div class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
          <h2 class="text-xl font-bold text-white">Recipe Notes</h2>
          <p class="mt-3 text-sm leading-7 text-slate-400">Vanilla workstation recipes are rendered with real Minecraft GUI art and slot overlays. Create and other processing recipes still use a custom machine-card layout for readability.</p>
        </div>
      </div>
    </section>

    <script src="assets/search.js"></script>
    <script>setupSearch("search", "results", "assets/search-index.json");</script>
    """
    (SITE_DIR / "index.html").write_text(page("JombiePack Catalog", body), encoding="utf-8")


def build_mod_index(mods: dict[str, ModEntry]) -> None:
    mod_dir = SITE_DIR / "mods"
    mod_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for mod in mods.values():
        icon = mod_icon_html(mod, "..")
        rows.append(
            f"<tr class='border-b border-slate-800/80 hover:bg-slate-800/40'>"
            f"<td class='py-4 pr-3'><div class='entry-head'>{icon}<div><a class='font-semibold text-white hover:text-sky-300' href='{safe_text(slugify(mod.mod_id))}.html'>{safe_text(mod.name)}</a><div class='mt-1 text-xs text-slate-500'>{safe_text(mod.project_summary or mod.description or 'No summary available.')}</div></div></div></td>"
            f"<td class='path py-4 pr-3 text-slate-300'>{safe_text(mod.mod_id)}</td><td class='py-4 text-slate-300'>{len(mod.item_ids)}</td></tr>"
        )
    body = f"""
    <div class="breadcrumbs text-sm text-slate-500"><a href="../index.html">Home</a> / Mods</div>
    <section class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
      <div class="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <div class="kicker">Browse</div>
          <h1 class="text-3xl font-black tracking-tight text-white">Mods in JombiePack</h1>
          <p class="mt-2 text-sm leading-6 text-slate-400">Every mod discovered from the pack index, with project links, docs, and local item presence.</p>
        </div>
        <div class="rounded-2xl border border-slate-700/50 bg-slate-800/60 px-4 py-3 text-sm text-slate-300">{len(mods)} total mods</div>
      </div>
      <div class="overflow-x-auto rounded-2xl border border-slate-800/80 bg-slate-950/40">
      <table class="list-table">
        <thead><tr><th class='text-left'>Name</th><th class='text-left'>Mod ID</th><th class='text-left'>Entries</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      </div>
    </section>
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
                <article class="rounded-3xl border border-slate-700/50 bg-slate-900/65 p-5 shadow-lg shadow-slate-950/20 transition hover:-translate-y-0.5 hover:border-sky-400/30 hover:bg-slate-900/85">
                  <div class="kicker">{safe_text(item.entry_type)}</div>
                  <div class="entry-head mt-3">
                    {icon}
                    <h3 class="text-base font-semibold text-white"><a class="hover:text-sky-300" href="../{safe_text(item_url(item.item_id))}">{safe_text(item.display_name)}</a></h3>
                  </div>
                  <div class="path mt-3 text-slate-400">{safe_text(item.item_id)}</div>
                  <div class="muted mt-2 text-sm">{len(item.recipes)} recipe(s)</div>
                </article>
                """
            )
        top_items = sorted((items[item_id] for item_id in mod.item_ids), key=lambda item: (-len(item.recipes), item.display_name.lower()))
        preferred = [item for item in top_items if item.namespace == mod.mod_id]
        fallback = [item for item in top_items if item.namespace != mod.mod_id]
        notable = (preferred + fallback)[:8]
        description = safe_text(mod.description) if mod.description else "No description was extracted from the jar metadata."
        summary = safe_text(mod.project_summary or mod.description or "No project summary was available.")
        excerpt = safe_text(mod.docs_excerpt or mod.project_body)
        links = []
        if mod.modrinth_url:
            links.append(f"<span class='chip'><a href='{safe_text(mod.modrinth_url)}'>Modrinth Page</a></span>")
        if mod.wiki_url:
            links.append(f"<span class='chip'><a href='{safe_text(mod.wiki_url)}'>Wiki</a></span>")
        if mod.source_url:
            links.append(f"<span class='chip'><a href='{safe_text(mod.source_url)}'>Source</a></span>")
        if mod.issues_url:
            links.append(f"<span class='chip'><a href='{safe_text(mod.issues_url)}'>Issues</a></span>")
        if mod.discord_url:
            links.append(f"<span class='chip'><a href='{safe_text(mod.discord_url)}'>Discord</a></span>")
        icon = mod_icon_html(mod, "..", large=True)
        info_chips = []
        if mod.categories:
            info_chips.extend(f"<span class='chip'>{safe_text(category)}</span>" for category in mod.categories[:6])
        if mod.client_side:
            info_chips.append(f"<span class='chip'>Client: {safe_text(mod.client_side)}</span>")
        if mod.server_side:
            info_chips.append(f"<span class='chip'>Server: {safe_text(mod.server_side)}</span>")
        if mod.downloads:
            info_chips.append(f"<span class='chip'>Downloads: {mod.downloads:,}</span>")
        docs_points = "".join(f"<li>{safe_text(point)}</li>" for point in mod.docs_points[:4])
        notable_cards = "".join(
            f"<article class='rounded-3xl border border-slate-700/50 bg-slate-900/65 p-5 shadow-lg shadow-slate-950/20 transition hover:-translate-y-0.5 hover:border-sky-400/30 hover:bg-slate-900/85'><div class='entry-head'>{item_icon_html(item.item_id, '..', items)}<div><h3 class='text-base font-semibold text-white'><a class='hover:text-sky-300' href='../{safe_text(item_url(item.item_id))}'>{safe_text(item.display_name)}</a></h3><div class='path mt-2 text-slate-400'>{safe_text(item.item_id)}</div><div class='muted mt-2 text-sm'>{len(item.recipes)} recipe(s)</div></div></div></article>"
            for item in notable
        )
        body = f"""
        <div class="breadcrumbs text-sm text-slate-500"><a href="../index.html">Home</a> / <a href="index.html">Mods</a> / {safe_text(mod.mod_id)}</div>
        <section class="relative overflow-hidden rounded-[32px] border border-slate-700/60 bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800 px-8 py-8 shadow-2xl shadow-slate-950/40">
          <div class="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(56,189,248,0.16),transparent_24%),radial-gradient(circle_at_bottom_left,rgba(34,197,94,0.12),transparent_22%)]"></div>
          <div class="relative">
          <div class="kicker">Mod Page</div>
          <div class="entry-head mt-3">
            {icon}
            <div>
              <h1 class="text-4xl font-black tracking-tight text-white">{safe_text(mod.name)}</h1>
              <p class="mt-3 max-w-3xl text-base leading-7 text-slate-300">{summary}</p>
            </div>
          </div>
          <div class="mt-6 flex flex-wrap gap-3">
            <span class="chip">Mod ID: {safe_text(mod.mod_id)}</span>
            <span class="chip">Version: {safe_text(mod.version or "unknown")}</span>
            <span class="chip">Entries: {len(mod.item_ids)}</span>
          </div>
          <div class="mt-5 flex flex-wrap gap-3">{''.join(links)}</div>
          <div class="mt-4 flex flex-wrap gap-3">{''.join(info_chips)}</div>
          </div>
        </section>
        <section class="mt-8 grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <div class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
            <h2 class="text-2xl font-bold text-white">About This Mod</h2>
            <p class="mt-4 text-sm leading-7 text-slate-300">{excerpt or description}</p>
            {"<p class='mt-4 text-sm text-slate-500'>Source: <a class='text-sky-300 hover:text-sky-200' href='" + safe_text(mod.docs_source_url) + "'>" + safe_text(mod.docs_source_url) + "</a></p>" if mod.docs_source_url else ""}
          </div>
          <div class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
            <h2 class="text-2xl font-bold text-white">Pack Presence</h2>
            <p class="mt-4 text-sm leading-7 text-slate-300">{safe_text(mod.name)} contributes {len(mod.item_ids)} cataloged item/block entries to JombiePack.</p>
            <p class="mt-3 text-sm leading-7 text-slate-400">{safe_text(mod.project_summary or mod.description or "This mod is present in the pack, but its exact gameplay role still needs a fuller pack-specific write-up.")}</p>
          </div>
        </section>
        <section class="mt-8 grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
          <div class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
            <h2 class="text-2xl font-bold text-white">Documentation Snapshot</h2>
            {"<ul class='mt-4 space-y-3 text-sm leading-7 text-slate-300'>" + docs_points + "</ul>" if docs_points else "<p class='mt-4 text-sm leading-7 text-slate-400'>No additional documentation summary could be extracted yet. Use the links above for the official docs or project page.</p>"}
          </div>
          <div class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
            <h2 class="text-2xl font-bold text-white">Notable Entries</h2>
            <div class="mt-5 grid gap-4 md:grid-cols-2">
            {notable_cards or "<p class='muted'>No high-visibility entries were detected for this mod yet, but it may still affect gameplay through systems, tweaks, or behind-the-scenes integrations.</p>"}
            </div>
          </div>
        </section>
        <section class="mt-8 rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
          <div class="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 class="text-2xl font-bold text-white">Items and Blocks</h2>
              <p class="mt-2 text-sm text-slate-400">Localized entries discovered for this mod from jars, recipes, and pack metadata.</p>
            </div>
          </div>
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {''.join(cards) or "<p class='muted'>No localized item entries were found for this mod yet.</p>"}
          </div>
        </section>
        """
        (mod_dir / f"{slugify(mod.mod_id)}.html").write_text(page(f"{mod.name} - JombiePack", body, rel_root=".."), encoding="utf-8")


def build_item_index(items: dict[str, ItemEntry]) -> None:
    item_dir = SITE_DIR / "items"
    item_dir.mkdir(parents=True, exist_ok=True)
    mods = sorted({item.owner_mod_id for item in items.values()})
    rows = []
    for item in items.values():
        icon = item_icon_html(item.item_id, "..", items)
        rows.append(
            f"<tr class='border-b border-slate-800/80 hover:bg-slate-800/40' data-name='{safe_text(item.display_name)}' data-id='{safe_text(item.item_id)}' data-mod='{safe_text(item.owner_mod_id)}' data-type='{safe_text(item.entry_type)}'>"
            f"<td class='py-4 pr-3'><div class='entry-head'>{icon}<div><a class='font-semibold text-white hover:text-sky-300' href='{safe_text(item.namespace)}/{safe_text(slugify(item.item_id.split(':', 1)[1]))}.html'>{safe_text(item.display_name)}</a><div class='mt-1 text-xs text-slate-500'>{safe_text(item.entry_type.title())}</div></div></div></td>"
            f"<td class='path py-4 pr-3 text-slate-300'>{safe_text(item.item_id)}</td>"
            f"<td class='py-4 pr-3'><a class='text-sky-300 hover:text-sky-200' href='../mods/{safe_text(slugify(item.owner_mod_id))}.html'>{safe_text(item.owner_mod_id)}</a></td>"
            f"<td class='py-4 pr-3 text-slate-300'>{len(item.recipes)}</td>"
            f"<td class='py-4 text-slate-300'>{safe_text(item.entry_type)}</td></tr>"
        )
    mod_options = "".join(f"<option value='{safe_text(mod_id)}'>{safe_text(mod_id)}</option>" for mod_id in mods)
    body = f"""
    <div class="breadcrumbs text-sm text-slate-500"><a href="../index.html">Home</a> / Items</div>
    <section class="rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
      <div class="mb-6">
        <div class="kicker">Browse</div>
        <h1 class="text-3xl font-black tracking-tight text-white">Items and Blocks</h1>
        <p class="mt-2 text-sm leading-6 text-slate-400">Filter the full catalog by mod, type, or registry ID to jump straight into item pages and recipe references.</p>
      </div>
      <div class="filter-row">
        <input id="item-filter-search" class="searchbox" placeholder="Filter by name or registry id">
        <select id="item-filter-mod"><option value="">All mods</option>{mod_options}</select>
        <select id="item-filter-type"><option value="">All types</option><option value="item">Items</option><option value="block">Blocks</option></select>
      </div>
      <div class="mt-6 overflow-x-auto rounded-2xl border border-slate-800/80 bg-slate-950/40">
      <table class="list-table">
        <thead><tr><th>Name</th><th>Registry ID</th><th>Mod</th><th>Recipes</th><th>Type</th></tr></thead>
        <tbody id="item-table-body">{''.join(rows)}</tbody>
      </table>
      </div>
    </section>
    <script src="../assets/search.js"></script>
    <script>setupItemFilters("item-filter-search", "item-filter-mod", "item-filter-type", "item-table-body");</script>
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
        usages_html = "".join(render_recipe(recipe, "../..", items) for recipe in item.usages)
        icon = item_icon_html(item.item_id, "../..", items, large=True)
        owner_name = mods[item.owner_mod_id].name if item.owner_mod_id in mods else item.owner_mod_id
        body = f"""
        <div class="breadcrumbs text-sm text-slate-500"><a href="../../index.html">Home</a> / <a href="../index.html">Items</a> / {safe_text(item.item_id)}</div>
        <section class="relative overflow-hidden rounded-[32px] border border-slate-700/60 bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800 px-8 py-8 shadow-2xl shadow-slate-950/40">
          <div class="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(56,189,248,0.16),transparent_24%),radial-gradient(circle_at_bottom_left,rgba(249,115,22,0.12),transparent_22%)]"></div>
          <div class="relative">
          <div class="kicker">{safe_text(item.entry_type)}</div>
          <div class="entry-head mt-3">
            {icon}
            <div>
              <h1 class="text-4xl font-black tracking-tight text-white">{safe_text(item.display_name)}</h1>
              <p class="mt-3 text-sm leading-7 text-slate-300">Registry entry, recipe page, and usage index for this item or block in JombiePack.</p>
            </div>
          </div>
          <div class="mt-6 flex flex-wrap gap-3">
            <span class="chip path">{safe_text(item.item_id)}</span>
            <span class="chip">Mod: <a href="../../mods/{safe_text(slugify(item.owner_mod_id))}.html">{safe_text(owner_name)}</a></span>
            <span class="chip">Recipe count: {len(item.recipes)}</span>
            <span class="chip">Used in: {len(item.usages)}</span>
          </div>
          </div>
        </section>
        <section class="mt-8 rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
          <div class="mb-5">
            <h2 class="text-2xl font-bold text-white">Recipes</h2>
            <p class="mt-2 text-sm text-slate-400">Known recipe outputs that create this entry.</p>
          </div>
          {recipes_html or "<p class='muted'>No recipe output was found in the scanned data for this entry.</p>"}
        </section>
        <section class="mt-8 rounded-[28px] border border-slate-700/50 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/20 backdrop-blur">
          <div class="mb-5">
            <h2 class="text-2xl font-bold text-white">Used In</h2>
            <p class="mt-2 text-sm text-slate-400">Recipes and processes that consume this entry as an ingredient.</p>
          </div>
          {usages_html or "<p class='muted'>No direct recipe usages were found for this entry.</p>"}
        </section>
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
    jar_paths, minecraft_client_jar, mods, items = load_catalog()
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    copy_assets()
    extract_gui_assets(minecraft_client_jar)
    extract_mod_icons(mods)
    extract_item_icons(jar_paths, items, minecraft_client_jar)
    enrich_mod_docs(mods)
    build_home(mods, items)
    build_mod_index(mods)
    build_mod_pages(mods, items)
    build_item_index(items)
    build_item_pages(mods, items)
    build_search_index(mods, items)
    print(f"Generated {len(mods)} mod pages and {len(items)} item pages in {SITE_DIR}")


if __name__ == "__main__":
    main()
