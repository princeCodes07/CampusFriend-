"use strict";

// Track the responsive header so navigation follows the search field and content stays clear.
const siteHeader = document.querySelector(".site-header");
if (siteHeader) {
  const navbar = siteHeader.querySelector(".navbar");
  const headerSearch = siteHeader.querySelector(".header-search");
  const headerBrand = siteHeader.querySelector(".brand");
  const updateHeaderLayout = () => {
    document.documentElement.style.setProperty("--site-header-height", `${Math.ceil(siteHeader.getBoundingClientRect().height)}px`);
    if (navbar && headerSearch) {
      const searchOffset = headerSearch.getBoundingClientRect().left - navbar.getBoundingClientRect().left;
      document.documentElement.style.setProperty("--header-search-offset", `${Math.max(0, searchOffset)}px`);
    }
  };
  updateHeaderLayout();
  const headerObserver = new ResizeObserver(updateHeaderLayout);
  headerObserver.observe(siteHeader);
  if (headerBrand) headerObserver.observe(headerBrand);
}

// Update one summary with server-calculated amounts; never calculate prices here.
const deliveryArea = document.querySelector('#checkout-form [name="delivery_area"]');
const deliveryQuotes = document.getElementById("delivery-quotes");
if (deliveryArea && deliveryQuotes) {
  const quotes = JSON.parse(deliveryQuotes.textContent);
  const updateDeliverySummary = () => {
    const quote = Object.hasOwn(quotes, deliveryArea.value) ? quotes[deliveryArea.value] : null;
    document.getElementById("delivery-summary-location").textContent = quote?.label || "Select your location";
    document.getElementById("delivery-summary-fee-row").hidden = Boolean(quote?.delivery_fee_separate);
    document.getElementById("delivery-summary-fee").textContent = quote ? `GH₵ ${quote.fee}` : "Select a location";
    document.getElementById("delivery-summary-total-label").textContent = quote?.delivery_fee_separate ? "Items total (delivery separate)" : "Final total";
    document.getElementById("delivery-summary-total").textContent = quote ? `GH₵ ${quote.total}` : "Select a location";
    const note = document.getElementById("delivery-summary-note");
    note.textContent = quote?.note || "";
    note.hidden = !quote?.note;
    for (const name of ["delivery_location", "landmark"]) {
      const field = document.querySelector(`#checkout-form [name="${name}"]`);
      if (field) field.required = Boolean(deliveryArea.value) && deliveryArea.value !== "pickup";
    }
  };
  deliveryArea.addEventListener("change", updateDeliverySummary);
  window.addEventListener("pageshow", updateDeliverySummary);
  updateDeliverySummary();
}

// Keep the menu usable without JavaScript; enhance it only when both elements exist.
const menuButton = document.querySelector(".menu-toggle");
const navigation = document.getElementById("primary-navigation");

if (menuButton && navigation) {
  const desktop = window.matchMedia("(min-width: 960px)");
  const setMenu = (open) => {
    navigation.dataset.open = String(open);
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  };

  navigation.dataset.collapsible = "true";
  menuButton.hidden = false;
  menuButton.addEventListener("click", () => {
    setMenu(menuButton.getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !desktop.matches && navigation.dataset.open === "true") {
      setMenu(false);
      menuButton.focus();
    }
  });
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a") && !desktop.matches) setMenu(false);
  });
  desktop.addEventListener("change", () => setMenu(false));
}

// Missing uploads must not leave broken-image icons or collapse product cards.
document.querySelectorAll("[data-product-image]").forEach((image) => {
  let replaced = false;
  const usePlaceholder = () => {
    if (replaced) return;
    replaced = true;
    image.alt = "Image unavailable for " + image.alt;
    image.src = image.dataset.fallback;
    image.classList.add("placeholder-image");
  };
  image.addEventListener("error", usePlaceholder, { once: true });
  if (image.complete && image.naturalWidth === 0) usePlaceholder();
});
