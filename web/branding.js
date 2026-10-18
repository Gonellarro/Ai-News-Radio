(() => {
  const node = (tag, text, cls) => { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; };
  async function refresh() {
    try {
      const response = await fetch("/api/branding"); const value = await response.json();
      if (!response.ok) throw new Error(value.error || "No se pudo leer la configuración visual.");
      document.getElementById("branding-status").textContent = `${value.brands.length} identidades · ${value.brands.filter(b => b.logo_url).length} con logotipo local · ${value.enabled ? "Tarjetas activas" : "Tarjetas desactivadas"}`;
      const list = document.getElementById("branding-list"); list.replaceChildren();
      for (const brand of value.brands) {
        const card = node("article", "", "panel");
        if (brand.logo_url) { const img = document.createElement("img"); img.src = brand.logo_url; img.alt = `Logo de ${brand.name}`; img.className = "brand-logo"; img.loading = "lazy"; card.append(img); }
        card.append(node("h3", brand.name));
        const color = node("div", "", "brand-swatch"); color.style.backgroundColor = brand.accent; card.append(color);
        card.append(node("p", brand.accent, "hint"), node("p", brand.domains.join(" · "), "hint brand-domains"));
        if (!brand.logo_url) card.append(node("p", "Identificación por nombre · Logotipo pendiente", "hint"));
        list.append(card);
      }
    } catch (error) { document.getElementById("branding-status").textContent = error.message; }
  }
  refresh();
})();
