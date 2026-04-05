async function setupSearch(inputId, resultsId, indexPath) {
  const input = document.getElementById(inputId);
  const results = document.getElementById(resultsId);
  if (!input || !results) return;

  let entries = [];
  try {
    const response = await fetch(indexPath);
    entries = await response.json();
  } catch (error) {
    results.innerHTML = "<p class='muted'>Search index could not be loaded.</p>";
    return;
  }

  const render = (query) => {
    const q = query.trim().toLowerCase();
    if (!q) {
      results.innerHTML = "";
      return;
    }

    const matches = entries
      .filter((entry) => {
        const hay = [entry.title, entry.kind, entry.mod, entry.id].join(" ").toLowerCase();
        return hay.includes(q);
      })
      .slice(0, 60);

    if (matches.length === 0) {
      results.innerHTML = "<p class='muted'>No results yet.</p>";
      return;
    }

    results.innerHTML = matches.map((entry) => `
      <div class="card">
        <div class="kicker">${entry.kind}</div>
        <h3><a href="${entry.url}">${entry.title}</a></h3>
        <div class="muted">${entry.mod || ""}</div>
        <div class="path">${entry.id || ""}</div>
      </div>
    `).join("");
  };

  input.addEventListener("input", () => render(input.value));
}

function setupItemFilters(searchId, modId, typeId, tableBodyId) {
  const search = document.getElementById(searchId);
  const mod = document.getElementById(modId);
  const type = document.getElementById(typeId);
  const tableBody = document.getElementById(tableBodyId);
  if (!search || !mod || !type || !tableBody) return;

  const rows = Array.from(tableBody.querySelectorAll("tr"));
  const apply = () => {
    const q = search.value.trim().toLowerCase();
    const modValue = mod.value;
    const typeValue = type.value;

    rows.forEach((row) => {
      const hay = [row.dataset.name, row.dataset.id, row.dataset.mod, row.dataset.type].join(" ").toLowerCase();
      const modOk = !modValue || row.dataset.mod === modValue;
      const typeOk = !typeValue || row.dataset.type === typeValue;
      const queryOk = !q || hay.includes(q);
      row.style.display = modOk && typeOk && queryOk ? "" : "none";
    });
  };

  search.addEventListener("input", apply);
  mod.addEventListener("change", apply);
  type.addEventListener("change", apply);
  apply();
}
