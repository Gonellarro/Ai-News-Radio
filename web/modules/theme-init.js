/* Apply the saved theme before loading the stylesheet to avoid a light/dark flash. */
(() => {
  let value = {};
  try {
    value = JSON.parse(localStorage.getItem("news-radio.appearance.v1")) || {};
  } catch {}
  document.documentElement.dataset.theme =
    value.mode === "light" ? "light" : "dark";
  document.documentElement.dataset.accent =
    typeof value.accent === "string" && /^[a-z]+$/.test(value.accent)
      ? value.accent
      : "green";
})();
