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
