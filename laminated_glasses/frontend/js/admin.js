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
}

function showLogin() {
  dashShell.classList.remove("open");
  loginScreen.style.display = "flex";
}

function logout() {
  state.token = null;
  localStorage.removeItem(TOKEN_KEY);
  showLogin();
}

document.getElementById("logoutBtn").addEventListener("click", logout);

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
          <td>${thumb}</td>
          <td>${escapeHtml(p.name)}</td>
          <td>${escapeHtml(p.category)}</td>
          <td>${formatPrice(p.cost_price)}</td>
          <td>${formatPrice(p.sale_price)}</td>
          <td class="${profitClass}">${formatPrice(p.profit)} (${p.profit_margin_percent}%)</td>
          <td><span class="pill-status ${p.is_active ? "on" : "off"}">${p.is_active ? "Faol" : "Yashirin"}</span></td>
          <td>
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
