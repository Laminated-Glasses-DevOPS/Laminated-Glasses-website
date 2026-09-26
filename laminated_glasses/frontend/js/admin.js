/* =========================================================
   Laminated Glasses — admin panel logikasi
   ========================================================= */

const API_BASE_URL = (() => {
  const { protocol, origin } = window.location;
  if (protocol === "http:" || protocol === "https:") return `${origin}/api`;
  return "http://localhost:8000/api";
})();

const TOKEN_KEY = "lg_admin_token";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || null,
  products: [],
  categories: [],
  orders: [],
  orderFilter: "",
};

/* ---------- Yordamchi funksiyalar ---------- */

function authHeaders(extra = {}) {
  return state.token ? { Authorization: `Bearer ${state.token}`, ...extra } : extra;
}

async function apiRequest(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...authHeaders(options.headers || {}),
    },
  });

  if (res.status === 401) {
    logout();
    throw new Error("Sessiya tugagan. Qaytadan kiring.");
  }

  if (!res.ok) {
    let detail = `Xatolik (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) detail = data.detail;
    } catch (_) {}
    throw new Error(detail);
  }

  if (res.status === 204) return null;
  return res.json();
}

function formatPrice(value) {
  const num = Math.round(Number(value) || 0);
  return num.toLocaleString("uz-UZ").replace(/[,\u00A0]/g, " ") + " so'm";
}

let toastTimer = null;
function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

/* ---------- Auth ---------- */

const loginScreen = document.getElementById("loginScreen");
const dashShell = document.getElementById("dashShell");

function showDashboard() {
  loginScreen.style.display = "none";
  dashShell.classList.add("open");
  loadEverything();
  startSecurityPolling();
}

function showLogin() {
  dashShell.classList.remove("open");
  loginScreen.style.display = "flex";
}

function logout() {
  state.token = null;
  localStorage.removeItem(TOKEN_KEY);
  stopSecurityPolling();
  showLogin();
}

document.getElementById("logoutBtn").addEventListener("click", logout);
document.getElementById("mobileLogoutBtn")?.addEventListener("click", logout);

/* ---------- Mobil: off-canvas menyu ---------- */

const sidebarPanel = document.getElementById("sidebarPanel");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const mobileMenuBtn = document.getElementById("mobileMenuBtn");
const mobileTopbarTitle = document.getElementById("mobileTopbarTitle");

function openMobileSidebar() {
  sidebarPanel?.classList.add("mobile-open");
  sidebarBackdrop?.classList.add("show");
  document.body.classList.add("no-scroll");
}
function closeMobileSidebar() {
  sidebarPanel?.classList.remove("mobile-open");
  sidebarBackdrop?.classList.remove("show");
  document.body.classList.remove("no-scroll");
}
mobileMenuBtn?.addEventListener("click", openMobileSidebar);
sidebarBackdrop?.addEventListener("click", closeMobileSidebar);

document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const password = document.getElementById("loginPassword").value;
  const errorEl = document.getElementById("loginError");
  const btn = document.getElementById("loginBtn");
  errorEl.textContent = "";
  btn.disabled = true;
  btn.textContent = "Tekshirilmoqda...";

  try {
    const res = await fetch(`${API_BASE_URL}/admin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Kirishda xatolik yuz berdi.");

    state.token = data.access_token;
    localStorage.setItem(TOKEN_KEY, state.token);
    document.getElementById("loginPassword").value = "";
    showDashboard();
  } catch (err) {
    errorEl.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Kirish";
  }
});

async function verifyExistingToken() {
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    await apiRequest("/admin/verify");
    showDashboard();
  } catch (err) {
    showLogin();
  }
}

/* ---------- Sidebar navigatsiya ---------- */

document.getElementById("sideNav").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (!btn) return;
  document.querySelectorAll(".side-nav button").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById(`view-${btn.dataset.view}`).classList.add("active");
  if (mobileTopbarTitle && btn.dataset.title) mobileTopbarTitle.textContent = btn.dataset.title;
  closeMobileSidebar();
});

/* ---------- Mahsulotlar ---------- */

const tableBody = document.getElementById("productsTableBody");

function noImageSVG() {
  return `<div class="table-thumb-empty"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 15 5-5 4 4 4-4 5 5"/></svg></div>`;
}

function renderProductsTable(filterText = "") {
  const filtered = state.products.filter((p) =>
    p.name.toLowerCase().includes(filterText.toLowerCase())
  );

  if (filtered.length === 0) {
    tableBody.innerHTML = `<tr class="empty-row"><td colspan="8">Mahsulot topilmadi.</td></tr>`;
    return;
  }

  tableBody.innerHTML = filtered
    .map((p) => {
      const profitClass = p.profit >= 0 ? "profit-positive" : "profit-negative";
      const thumb = p.image_url
        ? `<img class="table-thumb" src="${API_BASE_URL.replace(/\/api$/, "")}${p.image_url}" alt="" />`
        : noImageSVG();
      return `
        <tr data-id="${p.id}">
          <td data-label="">${thumb}</td>
          <td data-label="Nomi"><strong>${escapeHtml(p.name)}</strong></td>
          <td data-label="Kategoriya">${escapeHtml(p.category)}</td>
          <td data-label="Tannarx">${formatPrice(p.cost_price)}</td>
          <td data-label="Sotish narxi">${formatPrice(p.sale_price)}</td>
          <td data-label="Foyda" class="${profitClass}">${formatPrice(p.profit)} (${p.profit_margin_percent}%)</td>
          <td data-label="Holat"><span class="pill-status ${p.is_active ? "on" : "off"}">${p.is_active ? "Faol" : "Yashirin"}</span></td>
          <td data-label="">
            <div class="row-actions">
              <button class="icon-btn edit-btn" title="Tahrirlash">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
              </button>
              <button class="icon-btn danger delete-btn" title="O'chirish">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6"/></svg>
              </button>
            </div>
          </td>
        </tr>`;
    })
    .join("");

  tableBody.querySelectorAll(".edit-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const id = Number(e.target.closest("tr").dataset.id);
      const product = state.products.find((p) => p.id === id);
      if (product) openProductForm(product);
    });
  });

  tableBody.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const id = Number(e.target.closest("tr").dataset.id);
      const product = state.products.find((p) => p.id === id);
      if (product) confirmDeleteProduct(product);
    });
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function loadProducts() {
  try {
    state.products = await apiRequest("/admin/products");
    renderProductsTable(document.getElementById("productSearchAdmin").value);
  } catch (err) {
    showToast(err.message, true);
  }
}

document.getElementById("productSearchAdmin").addEventListener("input", (e) => {
  renderProductsTable(e.target.value);
});

async function confirmDeleteProduct(product) {
  if (!confirm(`"${product.name}" mahsulotini butunlay o'chirmoqchimisiz?`)) return;
  try {
    await apiRequest(`/admin/products/${product.id}`, { method: "DELETE" });
    showToast("Mahsulot o'chirildi.");
    await loadProducts();
    await loadStats();
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ---------- Mahsulot formasi (qo'shish / tahrirlash) ---------- */

const productFormOverlay = document.getElementById("productFormOverlay");
const productForm = document.getElementById("productForm");
const imagePreview = document.getElementById("imagePreview");
const imageDropText = document.getElementById("imageDropText");
let selectedImageFile = null;
let selectedImageFiles = [];
let editingProductId = null;

function openProductForm(product = null) {
  productForm.reset();
  selectedImageFile = null;
  selectedImageFiles = [];
  document.getElementById("imagePreviews").innerHTML = "";
  editingProductId = product ? product.id : null;
  document.getElementById("productFormError").textContent = "";
  document.getElementById("productFormTitle").textContent = product ? "Mahsulotni tahrirlash" : "Yangi mahsulot";

  if (product) {
    document.getElementById("productName").value = product.name;
    document.getElementById("productCategory").value = product.category;
    document.getElementById("productDescription").value = product.description || "";
    document.getElementById("productCostPrice").value = product.cost_price;
    document.getElementById("productSalePrice").value = product.sale_price;
    document.getElementById("productActive").checked = !!product.is_active;
    if (product.image_url) {
      imagePreview.src = `${API_BASE_URL.replace(/\/api$/, "")}${product.image_url}`;
      imagePreview.style.display = "block";
      imageDropText.textContent = `${(product.image_urls || [product.image_url]).length} ta saqlangan rasm. Yangilarini tanlab galereyani almashtiring.`;
      const previews = document.getElementById("imagePreviews");
      (product.image_urls || [product.image_url]).forEach((url) => {
        const img = document.createElement("img");
        img.src = `${API_BASE_URL.replace(/\/api$/, "")}${url}`;
        img.style.cssText = "width:64px;height:54px;object-fit:cover;border-radius:7px;margin:3px";
        previews.appendChild(img);
      });
    } else {
      imagePreview.style.display = "none";
      imageDropText.textContent = "Rasm tanlash uchun bosing (JPG, PNG, WEBP)";
    }
  } else {
    imagePreview.style.display = "none";
    imageDropText.textContent = "Rasm tanlash uchun bosing (JPG, PNG, WEBP)";
  }

  updateProfitPreview();
  populateCategoryOptions();
  productFormOverlay.classList.add("open");
}

function closeProductForm() {
  productFormOverlay.classList.remove("open");
}

document.getElementById("openAddProductBtn").addEventListener("click", () => openProductForm());
document.getElementById("cancelProductFormBtn").addEventListener("click", closeProductForm);
productFormOverlay.addEventListener("click", (e) => {
  if (e.target === productFormOverlay) closeProductForm();
});

document.getElementById("productImage").addEventListener("change", (e) => {
  selectedImageFiles = Array.from(e.target.files || []);
  selectedImageFile = selectedImageFiles[0] || null;
  const previews = document.getElementById("imagePreviews");
  previews.innerHTML = "";
  selectedImageFiles.forEach((file) => {
    const img = document.createElement("img");
    img.alt = file.name; img.title = file.name;
    img.style.cssText = "width:72px;height:60px;object-fit:cover;border-radius:8px;margin:4px";
    img.src = URL.createObjectURL(file); previews.appendChild(img);
  });
  if (selectedImageFiles.length) imageDropText.textContent = `${selectedImageFiles.length} ta rasm tanlandi`;
});

function updateProfitPreview() {
  const cost = Number(document.getElementById("productCostPrice").value) || 0;
  const sale = Number(document.getElementById("productSalePrice").value) || 0;
  const profit = sale - cost;
  const el = document.getElementById("profitPreviewValue");
  el.textContent = formatPrice(profit);
  el.style.color = profit >= 0 ? "#1c8a4f" : "#b3413f";
}

document.getElementById("productCostPrice").addEventListener("input", updateProfitPreview);
document.getElementById("productSalePrice").addEventListener("input", updateProfitPreview);

productForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("productFormError");
  const saveBtn = document.getElementById("saveProductBtn");
  errorEl.textContent = "";
  saveBtn.disabled = true;
  saveBtn.textContent = "Saqlanmoqda...";

  const formData = new FormData();
  formData.append("name", document.getElementById("productName").value.trim());
  formData.append("category", document.getElementById("productCategory").value.trim());
  formData.append("description", document.getElementById("productDescription").value.trim());
  formData.append("cost_price", document.getElementById("productCostPrice").value);
  formData.append("sale_price", document.getElementById("productSalePrice").value);
  formData.append("is_active", document.getElementById("productActive").checked ? "true" : "false");
  selectedImageFiles.forEach((file) => formData.append("images", file));

  try {
    if (editingProductId) {
      await apiRequest(`/admin/products/${editingProductId}`, { method: "PUT", body: formData });
      showToast("Mahsulot yangilandi.");
    } else {
      await apiRequest("/admin/products", { method: "POST", body: formData });
      showToast("Yangi mahsulot qo'shildi.");
    }
    closeProductForm();
    await loadProducts();
    await loadCategories();
    await loadStats();
  } catch (err) {
    errorEl.textContent = err.message;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Saqlash";
  }
});

/* ---------- Kategoriyalar ---------- */

function populateCategoryOptions() {
  const datalist = document.getElementById("categoryOptions");
  datalist.innerHTML = state.categories.map((c) => `<option value="${escapeHtml(c.name)}"></option>`).join("");
}

function renderCategoryChips() {
  const list = document.getElementById("categoryChipList");
  if (state.categories.length === 0) {
    list.innerHTML = `<p style="color:var(--navy-soft);font-size:0.85rem;">Hozircha kategoriya yo'q.</p>`;
    return;
  }
  list.innerHTML = state.categories
    .map(
      (c) => `<div class="category-chip" data-id="${c.id}">${escapeHtml(c.name)}<button title="O'chirish">✕</button></div>`
    )
    .join("");

  list.querySelectorAll(".category-chip button").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const chip = e.target.closest(".category-chip");
      const id = Number(chip.dataset.id);
      const category = state.categories.find((c) => c.id === id);
      if (!category) return;
      if (!confirm(`"${category.name}" kategoriyasini o'chirmoqchimisiz?`)) return;
      try {
        await apiRequest(`/admin/categories/${id}`, { method: "DELETE" });
        showToast("Kategoriya o'chirildi.");
        await loadCategories();
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

async function loadCategories() {
  try {
    state.categories = await apiRequest("/admin/categories");
    renderCategoryChips();
    populateCategoryOptions();
  } catch (err) {
    showToast(err.message, true);
  }
}

document.getElementById("addCategoryForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("newCategoryName");
  const name = input.value.trim();
  if (!name) return;
  try {
    await apiRequest("/admin/categories", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    input.value = "";
    showToast("Kategoriya qo'shildi.");
    await loadCategories();
  } catch (err) {
    showToast(err.message, true);
  }
});

/* ---------- Statistika ---------- */

async function loadStats() {
  try {
    const stats = await apiRequest("/admin/stats");
    document.getElementById("statTotalProducts").textContent = stats.total_products;
    document.getElementById("statActiveProducts").textContent = stats.active_products;
    document.getElementById("statTotalCategories").textContent = stats.total_categories;
    document.getElementById("statTotalCost").textContent = formatPrice(stats.total_potential_cost);
    document.getElementById("statTotalRevenue").textContent = formatPrice(stats.total_potential_revenue);
    document.getElementById("statTotalProfit").textContent = formatPrice(stats.total_potential_profit);
    document.getElementById("statAvgMargin").textContent = `${stats.average_profit_margin_percent}%`;
    document.getElementById("statTotalOrders").textContent = stats.total_orders;
    document.getElementById("statNewOrders").textContent = stats.new_orders;
    document.getElementById("statSoldOrders").textContent = stats.sold_orders;
    document.getElementById("statSoldRevenue").textContent = formatPrice(stats.sold_revenue);
    document.getElementById("statSoldProfit").textContent = formatPrice(stats.sold_profit);

    const badge = document.getElementById("newOrdersBadge");
    badge.textContent = stats.new_orders;
    badge.style.display = stats.new_orders > 0 ? "inline-block" : "none";
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ---------- Sozlamalar ---------- */

document.getElementById("changePasswordForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("passwordError");
  const successEl = document.getElementById("passwordSuccess");
  errorEl.textContent = "";
  successEl.textContent = "";

  const current = document.getElementById("currentPassword").value;
  const next = document.getElementById("newPassword").value;
  const confirmVal = document.getElementById("confirmPassword").value;

  if (next !== confirmVal) {
    errorEl.textContent = "Yangi parollar bir xil emas.";
    return;
  }

  try {
    await apiRequest("/admin/settings/password", {
      method: "PUT",
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    successEl.textContent = "Parol muvaffaqiyatli yangilandi.";
    e.target.reset();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById("telegramForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("telegramError");
  const successEl = document.getElementById("telegramSuccess");
  errorEl.textContent = "";
  successEl.textContent = "";

  const username = document.getElementById("telegramUsername").value.trim();

  try {
    await apiRequest("/admin/settings/telegram", {
      method: "PUT",
      body: JSON.stringify({ telegram_username: username }),
    });
    successEl.textContent = "Telegram username yangilandi.";
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

async function loadCurrentTelegram() {
  try {
    const contact = await apiRequest("/admin/settings/telegram");
    document.getElementById("telegramUsername").value = contact.telegram_username;
  } catch (err) {
    console.error(err);
  }
}

/* ---------- Buyurtmalar ---------- */

const STATUS_LABELS = {
  new: "Yangi",
  sold: "Sotildi",
  cancelled: "Bekor qilingan",
};

function formatDate(value) {
  if (!value) return "";
  const d = new Date(value.endsWith("Z") ? value : `${value}Z`);
  return d.toLocaleString("uz-UZ", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderOrders() {
  const list = document.getElementById("ordersList");
  const orders = state.orderFilter
    ? state.orders.filter((o) => o.status === state.orderFilter)
    : state.orders;

  if (orders.length === 0) {
    list.innerHTML = `<p class="empty-row" style="padding:26px;">Bu bo'limda buyurtma yo'q.</p>`;
    return;
  }

  list.innerHTML = orders
    .map((o) => {
      const items = o.items
        .map(
          (i) =>
            `<div><span>${escapeHtml(i.product_name)} × ${i.quantity}</span><span>${formatPrice(
              i.line_total
            )}</span></div>`
        )
        .join("");

      const actions =
        o.status === "new"
          ? `<div class="order-actions">
               <input type="text" placeholder="Bitta gap bilan izoh, masalan: Tovar topshirildi" data-note="${o.id}" maxlength="200" />
               <button class="btn btn-primary btn-sm" data-sold="${o.id}">Sotildi deb belgilash</button>
               <button class="btn btn-ghost btn-sm" data-cancel="${o.id}">Bekor qilish</button>
             </div>`
          : `<div class="order-actions">
               <button class="btn btn-ghost btn-sm" data-reopen="${o.id}">Yangi holatga qaytarish</button>
               <button class="btn btn-ghost btn-sm" data-delete="${o.id}">O'chirish</button>
             </div>`;

      const note = o.admin_note
        ? `<div class="order-note">Izoh: ${escapeHtml(o.admin_note)}</div>`
        : "";

      const confirmed = o.confirmed_at
        ? ` · tasdiqlangan: ${formatDate(o.confirmed_at)}`
        : "";

      return `
        <div class="order-card is-${o.status}">
          <div class="order-top">
            <div>
              <p class="order-customer">${escapeHtml(o.customer_name)}</p>
              <div class="order-meta">${o.code} · ${formatDate(o.created_at)}${confirmed}</div>
            </div>
            <span class="pill-status ${
            o.status === "sold" ? "on" : o.status === "new" ? "new" : "off"
          }">${STATUS_LABELS[o.status] || o.status}</span>
          </div>
          <div class="order-items">${items}</div>
          <div class="order-sum">
            <span>Jami</span>
            <span>${formatPrice(o.total_amount)} <span class="profit-positive">(foyda ${formatPrice(
        o.total_profit
      )})</span></span>
          </div>
          ${actions}
          ${note}
        </div>`;
    })
    .join("");

  list.querySelectorAll("[data-sold]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.sold);
      const input = list.querySelector(`[data-note="${id}"]`);
      const note = input ? input.value.trim() : "";
      if (!note) {
        showToast("Tasdiqlash uchun bitta gap bilan izoh yozing.", true);
        if (input) input.focus();
        return;
      }
      setOrderStatus(id, "sold", note);
    });
  });

  list.querySelectorAll("[data-cancel]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.cancel);
      const input = list.querySelector(`[data-note="${id}"]`);
      const note = input && input.value.trim() ? input.value.trim() : "Bekor qilindi.";
      if (!confirm("Buyurtma bekor qilinsinmi?")) return;
      setOrderStatus(id, "cancelled", note);
    });
  });

  list.querySelectorAll("[data-reopen]").forEach((btn) => {
    btn.addEventListener("click", () => setOrderStatus(Number(btn.dataset.reopen), "new", ""));
  });

  list.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Buyurtma tarixdan butunlay o'chirilsinmi?")) return;
      try {
        await apiRequest(`/admin/orders/${Number(btn.dataset.delete)}`, { method: "DELETE" });
        showToast("Buyurtma o'chirildi.");
        await loadOrders();
        await loadStats();
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

async function setOrderStatus(orderId, status, note) {
  try {
    await apiRequest(`/admin/orders/${orderId}`, {
      method: "PUT",
      body: JSON.stringify({ status, admin_note: note }),
    });
    showToast(status === "sold" ? "Buyurtma sotilgan deb belgilandi." : "Buyurtma holati yangilandi.");
    await loadOrders();
    await loadStats();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadOrders() {
  try {
    state.orders = await apiRequest("/admin/orders");
    renderOrders();
  } catch (err) {
    showToast(err.message, true);
  }
}

document.getElementById("orderFilters").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-status]");
  if (!btn) return;
  document
    .querySelectorAll("#orderFilters button")
    .forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  state.orderFilter = btn.dataset.status;
  renderOrders();
});

document.getElementById("refreshOrdersBtn").addEventListener("click", loadOrders);

/* ---------- Analitika (kunlik tashriflar) ---------- */

function renderVisitsChart(daily) {
  const container = document.getElementById("visitsChart");
  if (!daily || daily.length === 0) {
    container.innerHTML = `<p class="visits-chart-empty">Hozircha tashrif qayd etilmagan.</p>`;
    return;
  }

  const maxValue = Math.max(1, ...daily.map((d) => d.unique_visitors));
  const maxBarHeight = 150;
  const todayIso = new Date().toISOString().slice(0, 10);

  container.innerHTML = daily
    .map((d) => {
      const trunkHeight = Math.round((d.unique_visitors / maxValue) * maxBarHeight);
      const isToday = d.date === todayIso;
      return `
        <div class="visit-bar-col${isToday ? " visit-bar-today" : ""}" title="${d.label}: ${d.unique_visitors} ta noyob tashrif">
          <div class="visit-bar-count">${d.unique_visitors}</div>
          <div class="visit-bar-canopy${d.unique_visitors === 0 ? " zero" : ""}"></div>
          <div class="visit-bar-trunk" style="height:${Math.max(trunkHeight, 4)}px;"></div>
          <div class="visit-bar-ground"></div>
          <div class="visit-bar-label">${d.label}</div>
        </div>`;
    })
    .join("");
}

async function loadAnalytics() {
  try {
    const data = await apiRequest("/admin/analytics?days=14");
    document.getElementById("statTodayVisitors").textContent = data.today_visitors;
    document.getElementById("statYesterdayVisitors").textContent = data.yesterday_visitors;
    document.getElementById("statTotalDevices").textContent = data.total_unique_devices;
    document.getElementById("statTotalViews").textContent = data.total_views;
    renderVisitsChart(data.daily);
  } catch (err) {
    showToast(err.message, true);
  }
}

document.getElementById("refreshAnalyticsBtn").addEventListener("click", loadAnalytics);

/* ---------- Hammasini yuklash ---------- */

async function loadEverything() {
  await Promise.all([
    loadProducts(),
    loadCategories(),
    loadOrders(),
    loadStats(),
    loadAnalytics(),
    loadCurrentTelegram(),
  ]);
}

/* ---------- Init ---------- */

verifyExistingToken();

// News CRUD + contact/social links
async function loadAdminNews(){
 const list=document.getElementById('adminNewsList'); if(!list)return;
 try{const items=await apiRequest('/admin/news');list.innerHTML=items.length?items.map(n=>`<div style="display:flex;gap:12px;align-items:center;justify-content:space-between;padding:12px;border-bottom:1px solid var(--line);flex-wrap:wrap"><div><strong>${escapeHtml(n.title)}</strong><div class="sub">${n.is_published?'E’lon qilingan':'Qoralama'} · ${new Date(n.created_at).toLocaleDateString('uz-UZ')}</div></div><div><button class="btn btn-ghost btn-sm" data-edit-news="${n.id}">Tahrirlash</button> <button class="btn btn-ghost btn-sm" data-del-news="${n.id}">O‘chirish</button></div></div>`).join(''):'Hozircha yangilik yo‘q.';}catch(e){list.textContent=e.message;}
}
function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function closeNewsForm(){document.getElementById('newsFormOverlay').style.display='none';}
async function editNews(id=null){
 let old=null;
 if(id){old=(await apiRequest('/admin/news')).find(n=>n.id===id);if(!old)return;}
 document.getElementById('newsEditId').value=old?.id||'';
 document.getElementById('newsFormHeading').textContent=old?'Yangilikni tahrirlash':'Yangi yangilik qo‘shish';
 document.getElementById('newsTitle').value=old?.title||'';
 document.getElementById('newsExcerpt').value=old?.excerpt||'';
 document.getElementById('newsBody').value=old?.body||'';
 document.getElementById('newsImage').value=old?.image_url||'';
 document.getElementById('newsPublished').checked=old?!!old.is_published:true;
 document.getElementById('newsFormOverlay').style.display='flex';
 document.getElementById('newsTitle').focus();
}
document.getElementById('newsForm')?.addEventListener('submit',async e=>{
 e.preventDefault();const id=document.getElementById('newsEditId').value;
 const payload={title:document.getElementById('newsTitle').value.trim(),excerpt:document.getElementById('newsExcerpt').value.trim(),body:document.getElementById('newsBody').value.trim(),image_url:document.getElementById('newsImage').value.trim()||null,is_published:document.getElementById('newsPublished').checked};
 if(payload.title.length<2||!payload.body){showToast('Sarlavha va to‘liq matnni kiriting',true);return;}
 const btn=document.getElementById('saveNewsBtn');btn.disabled=true;btn.textContent='Saqlanmoqda…';
 try{await apiRequest(id?`/admin/news/${id}`:'/admin/news',{method:id?'PUT':'POST',body:JSON.stringify(payload)});closeNewsForm();showToast('Yangilik saqlandi');await loadAdminNews();}
 catch(err){showToast(err.message,true);}finally{btn.disabled=false;btn.textContent='Yangilikni saqlash';}
});
['closeNewsFormBtn','cancelNewsFormBtn'].forEach(id=>document.getElementById(id)?.addEventListener('click',closeNewsForm));
document.getElementById('newsFormOverlay')?.addEventListener('click',e=>{if(e.target.id==='newsFormOverlay')closeNewsForm();});
document.getElementById('addNewsBtn')?.addEventListener('click',()=>editNews());
document.getElementById('adminNewsList')?.addEventListener('click',async e=>{const edit=e.target.closest('[data-edit-news]'),del=e.target.closest('[data-del-news]');try{if(edit)await editNews(Number(edit.dataset.editNews));if(del&&confirm('Yangilikni o‘chirasizmi?')){await apiRequest(`/admin/news/${del.dataset.delNews}`,{method:'DELETE'});loadAdminNews();}}catch(err){showToast(err.message,true);}});
document.getElementById('sideNav')?.addEventListener('click',e=>{if(e.target.closest('[data-view="news"]')){loadAdminNews();loadSiteLinks();}});
async function loadSiteLinks(){try{const d=await apiRequest('/admin/site-links');({instagram:'linkInstagram',telegram:'linkTelegram',youtube:'linkYoutube',phone:'linkPhone',address:'linkAddress',email:'linkEmail'}&&Object.entries({instagram:'linkInstagram',telegram:'linkTelegram',youtube:'linkYoutube',phone:'linkPhone',address:'linkAddress',email:'linkEmail'}).forEach(([k,id])=>document.getElementById(id).value=d[k]||''));}catch(e){showToast(e.message,true);}}
document.getElementById('siteLinksForm')?.addEventListener('submit',async e=>{e.preventDefault();try{for(const [k,id] of Object.entries({instagram:'linkInstagram',telegram:'linkTelegram',youtube:'linkYoutube',phone:'linkPhone',address:'linkAddress',email:'linkEmail'}))await apiRequest(`/admin/site-links/${k}`,{method:'PUT',body:JSON.stringify({value:document.getElementById(id).value.trim()})});showToast('Aloqa ma’lumotlari saqlandi');}catch(err){showToast(err.message,true);}});

/* ---------- Xavfsizlik (honeypot: SQLi / XSS urinishlari, IP bo'yicha guruhlangan) ---------- */

state.lastSeenSecurityEventId = Number(localStorage.getItem('lg_last_seen_security_event') || 0);
state.securityPollTimer = null;
state.expandedIps = new Set();
state.honeypotMessagesByIp = {};
state.securityHeartbeats = {}; // backend'dan keladi: { ip: { online, last_seen_at } }

function formatSecurityDate(iso) {
  try {
    return new Date(iso).toLocaleString('uz-UZ', { dateStyle: 'short', timeStyle: 'medium' });
  } catch (e) {
    return iso;
  }
}

// IP haqiqatan onlaynmi -- honeypot 400-sahifasi shu IP dan hali ham ochiq
// turgan brauzerdan yuborayotgan "heartbeat" signaliga asoslanadi (backend:
// app/honeypot_state.py), oxirgi hujum vaqtiga emas. Shu tufayli brauzer
// yopilishi bilan (sendBeacon orqali) yoki heartbeat to'xtashi bilan (bir
// necha soniya ichida) holat "Oflayn"ga o'tadi.
function ipOnlineStatus(ip) {
  const hb = state.securityHeartbeats[ip];
  if (hb && hb.online) return { online: true, label: 'Onlayn', title: '' };
  const title = hb && hb.last_seen_at ? `Sahifadan oxirgi signal: ${formatSecurityDate(hb.last_seen_at)}` : 'Bu IP dan honeypot sahifasi ochilgani qayd etilmagan.';
  return { online: false, label: 'Oflayn', title };
}

function securityKindBadge(ev) {
  const label = ev.kind === 'sql_injection' ? 'SQL Injection' : `XSS${ev.xss_type ? ` — ${escapeHtml(ev.xss_type)}` : ''}`;
  const color = ev.kind === 'sql_injection' ? '#b3452f' : '#a3651f';
  return `<span class="kind-pill" style="background:${color};">${label}</span>`;
}

function formatHoneypotShown(msg) {
  if (!msg.shown_count) return 'Hali ko\'rilmagan';
  const when = msg.last_shown_at ? formatSecurityDate(msg.last_shown_at) : '';
  return `${msg.shown_count} marta${when ? ` — oxirgisi ${when}` : ''}`;
}

function renderIpMessageStatus(ip) {
  const msg = state.honeypotMessagesByIp[ip];
  if (!msg) {
    return `<div class="ip-msg-status empty">Bu IP ga hali shaxsiy xabar yuborilmagan.</div>`;
  }
  return `<div class="ip-msg-status active">
    <div class="ip-msg-text">${escapeHtml(msg.message)}</div>
    <div class="ip-msg-meta">
      <span>${msg.telegram_username ? '@' + escapeHtml(msg.telegram_username) : 'Telegram belgilanmagan'}</span>
      <span>${formatHoneypotShown(msg)}</span>
    </div>
    <button type="button" class="btn btn-ghost btn-sm" data-cancel-honeypot-msg="${msg.id}">Xabarni bekor qilish</button>
  </div>`;
}

function renderIpEventList(events) {
  return events
    .map(
      (ev) => `
    <div class="ip-event-row">
      <div class="ip-event-top">
        ${securityKindBadge(ev)}
        <span class="ip-event-time">${formatSecurityDate(ev.created_at)}</span>
      </div>
      <div class="ip-event-path">${escapeHtml(ev.method)} ${escapeHtml(ev.path)}</div>
      <div class="ip-event-sample">${escapeHtml(ev.matched_sample)}</div>
      <div class="ip-event-ua">${escapeHtml(ev.user_agent || '\u2014')}</div>
    </div>`
    )
    .join('');
}

function renderSecurityIpList(data) {
  document.getElementById('secTotal').textContent = data.total;
  document.getElementById('secSqlCount').textContent = data.sql_injection_count;
  document.getElementById('secXssCount').textContent = data.xss_count;

  const badge = document.getElementById('securityBadge');
  if (badge) {
    badge.textContent = data.total;
    badge.style.display = data.total > 0 ? 'inline-block' : 'none';
  }

  const container = document.getElementById('securityIpList');
  if (!container) return;

  if (!data.events.length) {
    const uniqueEl = document.getElementById('secUniqueIps');
    if (uniqueEl) uniqueEl.textContent = '0';
    container.innerHTML = `<p class="empty-row" style="padding:30px 18px;text-align:center;">Hozircha hech qanday hujum urinishi qayd etilmagan.</p>`;
    return;
  }

  const groups = new Map();
  data.events.forEach((ev) => {
    if (!groups.has(ev.ip_address)) groups.set(ev.ip_address, []);
    groups.get(ev.ip_address).push(ev);
  });

  const blocks = Array.from(groups.entries())
    .map(([ip, events]) => ({ ip, events, latest: events[0] }))
    .sort((a, b) => new Date(b.latest.created_at) - new Date(a.latest.created_at));

  const uniqueEl = document.getElementById('secUniqueIps');
  if (uniqueEl) uniqueEl.textContent = blocks.length;

  container.innerHTML = blocks
    .map(({ ip, events, latest }) => {
      const status = ipOnlineStatus(ip);
      const isOpen = state.expandedIps.has(ip);
      const hasActiveMsg = Boolean(state.honeypotMessagesByIp[ip]);
      const kindClass = latest.kind === 'sql_injection' ? 'is-sql' : 'is-xss';
      return `
      <div class="ip-block ${kindClass} ${isOpen ? 'open' : ''}" data-ip="${escapeHtml(ip)}">
        <div class="ip-block-header" data-toggle-ip="${escapeHtml(ip)}" role="button" tabindex="0" aria-expanded="${isOpen ? 'true' : 'false'}">
          <svg class="ip-block-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>
          <div class="ip-block-main">
            <div class="ip-block-line1">
              ${securityKindBadge(latest)}
              <span class="ip-block-ip">${escapeHtml(ip)}</span>
              ${events.length > 1 ? `<span class="ip-block-count">\u00d7${events.length}</span>` : ''}
              ${hasActiveMsg ? `<span class="ip-block-msg-dot" title="Faol xabar bor"></span>` : ''}
            </div>
            <div class="ip-block-line2">
              <span class="ip-block-time">${formatSecurityDate(latest.created_at)}</span>
              <span class="ip-block-status ${status.online ? 'online' : 'offline'}" title="${escapeHtml(status.title)}"><i></i>${status.label}</span>
            </div>
          </div>
          <button type="button" class="ip-block-arrow" data-open-honeypot-msg="${escapeHtml(ip)}" title="Xabar yozish">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          </button>
        </div>
        <div class="ip-block-detail"${isOpen ? '' : ' hidden'}>
          ${renderIpMessageStatus(ip)}
          <div class="ip-event-list">${renderIpEventList(events)}</div>
        </div>
      </div>`;
    })
    .join('');
}

async function loadSecurityEvents({ notify = false } = {}) {
  try {
    const [data, messages] = await Promise.all([
      apiRequest('/admin/security-events?limit=300'),
      apiRequest('/admin/security/messages').catch(() => []),
    ]);

    state.honeypotMessagesByIp = {};
    (messages || []).forEach((m) => {
      state.honeypotMessagesByIp[m.ip_address] = m;
    });
    state.securityHeartbeats = data.heartbeats || {};

    renderSecurityIpList(data);

    if (notify && data.events.length) {
      const newest = data.events[0];
      if (newest.id > state.lastSeenSecurityEventId) {
        const isFirstLoad = state.lastSeenSecurityEventId === 0;
        state.lastSeenSecurityEventId = newest.id;
        localStorage.setItem('lg_last_seen_security_event', String(newest.id));
        if (!isFirstLoad) {
          const label = newest.kind === 'sql_injection' ? 'SQL Injection' : `XSS (${newest.xss_type || ''})`;
          showToast(`Yangi hujum urinishi ushlandi: ${label} \u2014 IP ${newest.ip_address}`, true);
        }
      }
    }
  } catch (err) {
    const container = document.getElementById('securityIpList');
    if (container) container.innerHTML = `<p class="empty-row" style="padding:30px 18px;text-align:center;">${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById('refreshSecurityBtn')?.addEventListener('click', () => loadSecurityEvents({ notify: false }));
document.getElementById('sideNav')?.addEventListener('click', (e) => {
  if (e.target.closest('[data-view="security"]')) loadSecurityEvents({ notify: false });
});

// Honeypot sahifasi har 4 soniyada heartbeat yuboradi (backend:
// HEARTBEAT_INTERVAL_SECONDS), shuning uchun admin panel ham Onlayn/Oflayn
// holati "real-vaqt" tuyulishi uchun tez-tez (8 soniyada bir) so'raydi.
function startSecurityPolling() {
  if (state.securityPollTimer) return;
  loadSecurityEvents({ notify: true });
  state.securityPollTimer = setInterval(() => loadSecurityEvents({ notify: true }), 8000);
}
function stopSecurityPolling() {
  if (state.securityPollTimer) {
    clearInterval(state.securityPollTimer);
    state.securityPollTimer = null;
  }
}

/* ---------- IP blokini ochish/yopish va honeypot xabar amallari ---------- */

document.getElementById('securityIpList')?.addEventListener('click', (e) => {
  const openBtn = e.target.closest('[data-open-honeypot-msg]');
  if (openBtn) {
    openHoneypotMsgModal(openBtn.dataset.openHoneypotMsg);
    return;
  }

  const cancelBtn = e.target.closest('[data-cancel-honeypot-msg]');
  if (cancelBtn) {
    if (!confirm('Bu xabarni bekor qilasizmi? Hujumchi endi standart javobni ko\'radi.')) return;
    (async () => {
      try {
        await apiRequest(`/admin/security/messages/${cancelBtn.dataset.cancelHoneypotMsg}`, { method: 'DELETE' });
        showToast('Xabar bekor qilindi.');
        loadSecurityEvents({ notify: false });
      } catch (err) {
        showToast(err.message, true);
      }
    })();
    return;
  }

  const header = e.target.closest('[data-toggle-ip]');
  if (header) {
    const ip = header.dataset.toggleIp;
    const block = header.closest('.ip-block');
    const detail = block?.querySelector('.ip-block-detail');
    if (!block || !detail) return;
    const isOpen = block.classList.toggle('open');
    detail.hidden = !isOpen;
    header.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    if (isOpen) state.expandedIps.add(ip);
    else state.expandedIps.delete(ip);
  }
});

document.getElementById('securityIpList')?.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  // Strelka (xabar yozish) yoki bekor qilish tugmasi o'zining tabiiy
  // click xatti-harakatiga ega -- bu yerda faqat sarlavhaning o'zi
  // fokusda bo'lganda (nested tugmalar emas) blokni ochamiz/yopamiz.
  const header = e.target.closest('[data-toggle-ip]');
  if (!header || e.target !== header) return;
  e.preventDefault();
  header.click();
});

document.getElementById('clearSecurityLogsBtn')?.addEventListener('click', async () => {
  if (!confirm('Xavfsizlik jurnalidagi barcha yozuvlar butunlay o\'chiriladi. Davom etasizmi?')) return;
  try {
    const res = await apiRequest('/admin/security-events', { method: 'DELETE' });
    showToast(`${res.deleted} ta yozuv o'chirildi.`);
    state.expandedIps.clear();
    loadSecurityEvents({ notify: false });
  } catch (err) {
    showToast(err.message, true);
  }
});

/* ---------- Honeypot: hujumchiga shaxsiy xabar yozish ---------- */

const honeypotMsgOverlay = document.getElementById('honeypotMsgOverlay');
const honeypotMsgForm = document.getElementById('honeypotMsgForm');

function openHoneypotMsgModal(ip) {
  document.getElementById('honeypotMsgIp').textContent = ip;
  honeypotMsgForm.dataset.ip = ip;
  const existing = state.honeypotMessagesByIp[ip];
  const note = document.getElementById('honeypotMsgExistingNote');
  if (existing) {
    document.getElementById('honeypotMsgText').value = existing.message;
    document.getElementById('honeypotMsgTelegram').value = existing.telegram_username || '';
    if (note) {
      note.textContent = 'Bu IP uchun faol xabar allaqachon bor \u2014 yuborsangiz eskisi shu bilan almashtiriladi.';
      note.style.display = 'block';
    }
  } else {
    document.getElementById('honeypotMsgText').value = '';
    document.getElementById('honeypotMsgTelegram').value = '';
    if (note) note.style.display = 'none';
  }
  honeypotMsgOverlay.classList.add('open');
}

function closeHoneypotMsgModal() {
  honeypotMsgOverlay.classList.remove('open');
}

document.getElementById('cancelHoneypotMsgBtn')?.addEventListener('click', closeHoneypotMsgModal);
honeypotMsgOverlay?.addEventListener('click', (e) => {
  if (e.target === honeypotMsgOverlay) closeHoneypotMsgModal();
});

honeypotMsgForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const ip = honeypotMsgForm.dataset.ip;
  const message = document.getElementById('honeypotMsgText').value.trim();
  const telegram_username = document.getElementById('honeypotMsgTelegram').value.trim() || null;
  if (!ip || !message) return;
  try {
    await apiRequest('/admin/security/messages', {
      method: 'POST',
      body: JSON.stringify({ ip_address: ip, message, telegram_username }),
    });
    showToast(`Xabar ${ip} uchun yuborildi.`);
    closeHoneypotMsgModal();
    state.expandedIps.add(ip);
    loadSecurityEvents({ notify: false });
  } catch (err) {
    showToast(err.message, true);
  }
});

/* ---------- Konstruktor o'lchamlari ---------- */

state.constructorSizes = [];

function fmtNum(n) {
  return n % 1 === 0 ? String(n) : n.toFixed(1);
}

function sizePanes(s) {
  if (Array.isArray(s.panes) && s.panes.length) return s.panes;
  const count = Number(s.pane_count) || 1;
  return Array.from({ length: count }, () => ({ width_cm: s.width_cm, height_cm: s.height_cm }));
}

function dimLabel(s) {
  const panes = sizePanes(s);
  const allSame = panes.every((p) => p.width_cm === panes[0].width_cm && p.height_cm === panes[0].height_cm);
  if (allSame) return `${fmtNum(panes[0].width_cm)} x ${fmtNum(panes[0].height_cm)} sm`;
  return panes.map((p) => `${fmtNum(p.width_cm)}×${fmtNum(p.height_cm)}`).join(', ');
}

function totalDimLabel(s) {
  const panes = sizePanes(s);
  const totalW = panes.reduce((sum, p) => sum + p.width_cm, 0);
  const maxH = Math.max(...panes.map((p) => p.height_cm));
  return `${fmtNum(totalW)} x ${fmtNum(maxH)} sm`;
}

/* ---- Har bir oynaning eni/bo'yini alohida sozlash uchun dinamik ro'yxat
   (yangi o'lcham qo'shish formasida) -- index.html prototipidagi
   panelList mantig'i bilan bir xil. ---- */
function renderNewSizePanesList() {
  const wrap = document.getElementById('newSizePanesList');
  if (!wrap) return;
  const count = Math.max(1, Math.min(20, Number(document.getElementById('newSizePaneCount').value) || 1));

  const old = [...wrap.querySelectorAll('[data-pane]')].map((row) => ({
    w: row.querySelector('.pane-w')?.value,
    h: row.querySelector('.pane-h')?.value,
  }));

  wrap.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const saved = old[i] || {};
    const row = document.createElement('div');
    row.dataset.pane = String(i + 1);
    row.style.cssText = 'display:grid;grid-template-columns:26px 1fr 1fr;gap:8px;align-items:center;';
    row.innerHTML = `
      <span style="font-size:11px;font-weight:700;color:var(--navy-soft);text-align:center;">${i + 1}</span>
      <input type="number" class="pane-w" min="1" max="1000" step="0.5" placeholder="Eni (sm)" value="${saved.w ?? ''}" required />
      <input type="number" class="pane-h" min="1" max="1000" step="0.5" placeholder="Bo'yi (sm)" value="${saved.h ?? ''}" required />
    `;
    wrap.appendChild(row);
  }
}

function collectNewSizePanes() {
  const wrap = document.getElementById('newSizePanesList');
  if (!wrap) return [];
  return [...wrap.querySelectorAll('[data-pane]')].map((row) => ({
    width_cm: Number(row.querySelector('.pane-w').value),
    height_cm: Number(row.querySelector('.pane-h').value),
  }));
}

document.getElementById('newSizePaneCount')?.addEventListener('input', renderNewSizePanesList);
renderNewSizePanesList();

function renderConstructorSizesTable() {
  const body = document.getElementById('constructorSizesTableBody');
  if (!body) return;
  if (!state.constructorSizes.length) {
    body.innerHTML = `<tr class="empty-row"><td colspan="7">Hozircha o'lcham qo'shilmagan.</td></tr>`;
    return;
  }
  body.innerHTML = state.constructorSizes
    .map((s) => `
      <tr data-id="${s.id}">
        <td data-label="Nomi"><strong>${escapeHtml(s.label)}</strong></td>
        <td data-label="Oynalar">${s.pane_count || 1} ta</td>
        <td data-label="Har biri">${dimLabel(s)}</td>
        <td data-label="Umumiy">${totalDimLabel(s)}</td>
        <td data-label="Narxi">${s.price ? formatPrice(s.price) : "—"}</td>
        <td data-label="Holat"><span class="pill-status toggle-active-size ${s.is_active ? 'on' : 'off'}" style="cursor:pointer;" title="Holatni almashtirish">${s.is_active ? 'Faol' : 'Yashirin'}</span></td>
        <td data-label="">
          <div class="row-actions">
            <button class="icon-btn danger delete-size-btn" title="O'chirish">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6"/></svg>
            </button>
          </div>
        </td>
      </tr>`)
    .join('');

  body.querySelectorAll('.toggle-active-size').forEach((el) => {
    el.addEventListener('click', async (e) => {
      const id = Number(e.target.closest('tr').dataset.id);
      const size = state.constructorSizes.find((s) => s.id === id);
      if (!size) return;
      try {
        await apiRequest(`/admin/constructor/sizes/${id}`, {
          method: 'PUT',
          body: JSON.stringify({ is_active: !size.is_active }),
        });
        await loadConstructorSizes();
        showToast('Holat yangilandi');
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });

  body.querySelectorAll('.delete-size-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const id = Number(e.target.closest('tr').dataset.id);
      const size = state.constructorSizes.find((s) => s.id === id);
      if (!size) return;
      if (!confirm(`"${size.label}" o'lchamini o'chirasizmi?`)) return;
      try {
        await apiRequest(`/admin/constructor/sizes/${id}`, { method: 'DELETE' });
        await loadConstructorSizes();
        showToast("O'lcham o'chirildi");
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

async function loadConstructorSizes() {
  const body = document.getElementById('constructorSizesTableBody');
  try {
    state.constructorSizes = await apiRequest('/admin/constructor/sizes');
    renderConstructorSizesTable();
  } catch (err) {
    if (body) body.innerHTML = `<tr class="empty-row"><td colspan="5">${escapeHtml(err.message)}</td></tr>`;
  }
}

document.getElementById('addConstructorSizeForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById('constructorSizeFormError');
  errorBox.textContent = '';

  const label = document.getElementById('newSizeLabel').value.trim();
  const panes = collectNewSizePanes();
  const priceRaw = document.getElementById('newSizePrice').value;
  const price = priceRaw ? Number(priceRaw) : 0;

  const invalidPane = panes.some((p) => !p.width_cm || !p.height_cm);
  if (!label || !panes.length || invalidPane) {
    errorBox.textContent = "Nomi va har bir oynaning eni/bo'yini to'ldiring.";
    return;
  }

  const btn = e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    await apiRequest('/admin/constructor/sizes', {
      method: 'POST',
      body: JSON.stringify({ label, panes, price, is_active: true }),
    });
    e.target.reset();
    renderNewSizePanesList();
    await loadConstructorSizes();
    showToast("O'lcham qo'shildi");
  } catch (err) {
    errorBox.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('sideNav')?.addEventListener('click', (e) => {
  if (e.target.closest('[data-view="constructor"]')) loadConstructorSizes();
});

/* ---------- Zaxira nusxalar (backups) ---------- */

function backupEmptyState() {
  return `<p class="state-msg">Hozircha hech qanday zaxira fayli yo'q. Fayllar tozalash tsikli oldidan (buyurtmalar/yangiliklar — 48 soatda, xavfsizlik jurnali — 24 soatda) avtomatik paydo bo'ladi.</p>`;
}

function renderBackupsList(items) {
  const holder = document.getElementById("backupsList");
  if (!items.length) {
    holder.innerHTML = backupEmptyState();
    return;
  }
  holder.innerHTML = items
    .map(
      (b) => `
      <div class="backup-row" data-filename="${escapeHtml(b.filename)}">
        <div class="backup-row-info">
          <strong>${escapeHtml(b.section_label)}</strong>
          <span class="sub">${formatDate(b.created_at)} · ${b.size_kb} KB</span>
        </div>
        <button class="btn btn-primary btn-sm backup-download-btn">Yuklab olish (.xlsx)</button>
      </div>`
    )
    .join("");

  holder.querySelectorAll(".backup-download-btn").forEach((btn) => {
    btn.addEventListener("click", () => downloadBackup(btn));
  });
}

async function loadBackups() {
  const holder = document.getElementById("backupsList");
  holder.innerHTML = `<p class="state-msg">Yuklanmoqda...</p>`;
  try {
    const items = await apiRequest("/admin/backups");
    renderBackupsList(items);
  } catch (err) {
    holder.innerHTML = `<p class="state-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function downloadBackup(btn) {
  const row = btn.closest(".backup-row");
  const filename = row.dataset.filename;
  btn.disabled = true;
  btn.textContent = "Yuklanmoqda...";
  try {
    // Bu fayl himoyalangan endpoint (Bearer token talab qiladi), shuning
    // uchun oddiy <a href> havola ishlamaydi -- brauzer sahifa navigatsiyasida
    // maxsus headerlarni yubora olmaydi. Shu sabab fetch orqali blob sifatida
    // olib, keyin vaqtinchalik havola orqali yuklab olamiz.
    const res = await fetch(`${API_BASE_URL}/admin/backups/${encodeURIComponent(filename)}/download`, {
      headers: authHeaders(),
    });
    if (res.status === 401) {
      logout();
      throw new Error("Sessiya tugagan. Qaytadan kiring.");
    }
    if (!res.ok) {
      let detail = `Xatolik (${res.status})`;
      try {
        const data = await res.json();
        if (data.detail) detail = data.detail;
      } catch (_) {}
      throw new Error(detail);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    showToast("Zaxira fayli yuklab olindi. Server tarafida u endi o'chirildi.");
    // Fayl serverda avtomatik o'chirilgani uchun ro'yxatni yangilaymiz.
    row.remove();
    if (!document.querySelectorAll(".backup-row").length) {
      document.getElementById("backupsList").innerHTML = backupEmptyState();
    }
  } catch (err) {
    showToast(err.message, true);
    btn.disabled = false;
    btn.textContent = "Yuklab olish (.xlsx)";
  }
}

document.getElementById("refreshBackupsBtn")?.addEventListener("click", loadBackups);
document.getElementById("sideNav")?.addEventListener("click", (e) => {
  if (e.target.closest('[data-view="backups"]')) loadBackups();
});

/* ---------- Baza holati (Database status) ---------- */

function formatSizeKb(kb) {
  const num = Number(kb) || 0;
  if (num >= 1024 * 1024) return `${(num / (1024 * 1024)).toFixed(2)} GB`;
  if (num >= 1024) return `${(num / 1024).toFixed(1)} MB`;
  return `${num.toFixed(0)} KB`;
}

function renderStorageBars(status) {
  const holder = document.getElementById("dbStorageBars");
  const rows = [
    { label: "Baza fayli (.db)", value: status.db_size_kb },
    { label: "Yuklangan rasmlar (uploads)", value: status.uploads_size_kb },
    { label: "Excel zaxiralar (backups)", value: status.backups_size_kb },
  ];
  const diskPercent = status.disk_used_percent || 0;
  const warnClass = diskPercent >= 85 ? " warn" : "";

  holder.innerHTML = `
    <div class="storage-bar-row">
      <div class="storage-bar-label">
        <span>Umumiy disk</span>
        <span>${formatSizeKb(status.disk_used_kb)} / ${formatSizeKb(status.disk_total_kb)} (${diskPercent}%)</span>
      </div>
      <div class="storage-bar-track"><div class="storage-bar-fill${warnClass}" style="width:${Math.min(100, diskPercent)}%"></div></div>
    </div>
    ${rows
      .map(
        (r) => `
      <div class="storage-bar-row">
        <div class="storage-bar-label"><span>${escapeHtml(r.label)}</span><span>${formatSizeKb(r.value)}</span></div>
      </div>`
      )
      .join("")}
    ${
      status.last_snapshot_at
        ? `<p class="sub" style="margin-top:8px;">Oxirgi avtomatik zaxira: ${formatDate(status.last_snapshot_at)}</p>`
        : ""
    }
  `;
}

function renderTableCounts(tables) {
  const holder = document.getElementById("dbTableCounts");
  if (!tables || !tables.length) {
    holder.innerHTML = `<p class="state-msg">Ma'lumot yo'q.</p>`;
    return;
  }
  holder.innerHTML = tables
    .map(
      (t) => `
      <div class="db-table-count-row">
        <span>${escapeHtml(t.label)}</span>
        <strong>${t.rows.toLocaleString("uz-UZ")}</strong>
      </div>`
    )
    .join("");
}

async function loadDatabaseStatus() {
  try {
    const status = await apiRequest("/admin/database/status");
    renderStorageBars(status);
    renderTableCounts(status.tables);
  } catch (err) {
    document.getElementById("dbStorageBars").innerHTML = `<p class="state-msg">${escapeHtml(err.message)}</p>`;
    document.getElementById("dbTableCounts").innerHTML = "";
  }
}

function dbSnapshotEmptyState() {
  return `<p class="state-msg">Hozircha avtomatik zaxira nusxa yo'q -- bu yerga faqat bazani "tiklash" amalidan oldin yozuv qo'shiladi.</p>`;
}

async function loadDbSnapshots() {
  const holder = document.getElementById("dbSnapshotsList");
  holder.innerHTML = `<p class="state-msg">Yuklanmoqda...</p>`;
  try {
    const items = await apiRequest("/admin/database/snapshots");
    if (!items.length) {
      holder.innerHTML = dbSnapshotEmptyState();
      return;
    }
    holder.innerHTML = items
      .map(
        (s) => `
      <div class="backup-row" data-filename="${escapeHtml(s.filename)}">
        <div class="backup-row-info">
          <strong>Bazaning avtomatik zaxirasi</strong>
          <span class="sub">${formatDate(s.created_at)} · ${formatSizeKb(s.size_kb)}</span>
        </div>
        <button class="btn btn-ghost btn-sm db-snapshot-download-btn">Yuklab olish (.db)</button>
      </div>`
      )
      .join("");
    holder.querySelectorAll(".db-snapshot-download-btn").forEach((btn) => {
      btn.addEventListener("click", () => downloadDbSnapshot(btn));
    });
  } catch (err) {
    holder.innerHTML = `<p class="state-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function downloadBlobAuthed(url, filename, btn, busyText, idleText) {
  btn.disabled = true;
  btn.textContent = busyText;
  try {
    const res = await fetch(url, { headers: authHeaders() });
    if (res.status === 401) {
      logout();
      throw new Error("Sessiya tugagan. Qaytadan kiring.");
    }
    if (!res.ok) {
      let detail = `Xatolik (${res.status})`;
      try {
        const data = await res.json();
        if (data.detail) detail = data.detail;
      } catch (_) {}
      throw new Error(detail);
    }
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objUrl);
    return true;
  } catch (err) {
    showToast(err.message, true);
    return false;
  } finally {
    btn.disabled = false;
    btn.textContent = idleText;
  }
}

async function downloadDbSnapshot(btn) {
  const row = btn.closest(".backup-row");
  const filename = row.dataset.filename;
  const ok = await downloadBlobAuthed(
    `${API_BASE_URL}/admin/database/snapshots/${encodeURIComponent(filename)}/download`,
    filename,
    btn,
    "Yuklanmoqda...",
    "Yuklab olish (.db)"
  );
  if (ok) showToast("Zaxira nusxa yuklab olindi.");
}

document.getElementById("downloadDbBtn")?.addEventListener("click", async () => {
  const btn = document.getElementById("downloadDbBtn");
  const filename = `laminated_glasses_${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "")}.db`;
  const ok = await downloadBlobAuthed(
    `${API_BASE_URL}/admin/database/download`,
    filename,
    btn,
    "Tayyorlanmoqda...",
    "Bazani yuklab olish (.db)"
  );
  if (ok) showToast("Baza fayli yuklab olindi. Uni xavfsiz joyga saqlang.");
});

document.getElementById("restoreDbForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("restoreDbFile");
  const passwordInput = document.getElementById("restoreDbPassword");
  const file = fileInput.files[0];
  if (!file) return;

  const confirmed = window.confirm(
    "DIQQAT: joriy bazadagi BARCHA mahsulot, buyurtma va sozlamalar yuklangan fayl bilan ALMASHTIRILADI. " +
      "Bu amalni bekor qilib bo'lmaydi (faqat avtomatik zaxiradan qo'lda tiklash mumkin). Davom etasizmi?"
  );
  if (!confirmed) return;

  const btn = document.getElementById("restoreDbBtn");
  btn.disabled = true;
  btn.textContent = "Tiklanmoqda...";

  const formData = new FormData();
  formData.append("file", file);
  formData.append("current_password", passwordInput.value);

  try {
    const status = await apiRequest("/admin/database/restore", {
      method: "POST",
      body: formData,
    });
    renderStorageBars(status);
    renderTableCounts(status.tables);
    passwordInput.value = "";
    fileInput.value = "";
    showToast("Baza muvaffaqiyatli tiklandi.");
    loadDbSnapshots();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Bazani tiklash";
  }
});

document.getElementById("refreshDbStatusBtn")?.addEventListener("click", () => {
  loadDatabaseStatus();
  loadDbSnapshots();
});
document.getElementById("sideNav")?.addEventListener("click", (e) => {
  if (e.target.closest('[data-view="database"]')) {
    loadDatabaseStatus();
    loadDbSnapshots();
  }
});
