/* Laminated Glasses — ommaviy sayt logikasi.
   Tashqi kutubxonasiz vanilla JS: eng kuchsiz telefonlarda ham tez ishlaydi. */

const API_BASE_URL = (() => {
  const { protocol, origin } = window.location;
  // Sayt backend bilan bitta portdan berilsa (odatiy holat), shu manzil ishlatiladi.
  if (protocol === "http:" || protocol === "https:") return `${origin}/api`;
  // Fayl sifatida ochilgan bo'lsa (file://) — lokal serverga murojaat.
  return "http://localhost:8000/api";
})();

const MEDIA_BASE = API_BASE_URL.replace(/\/api$/, "");
const DEVICE_KEY = "lg_device_id";
const TOKEN_KEY = "lg_customer_token";

/* Sessiya tokeni (Google orqali kirgandan keyin server beradi). Brauzerda
   saqlash cheklangan bo'lishi mumkin (maxfiy rejim) — xato bo'lsa sayt
   ishlashda davom etadi, faqat sessiya sahifa yopilguncha turadi. */
function loadToken() {
  try { return localStorage.getItem(TOKEN_KEY) || null; } catch (_) { return null; }
}
function saveToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (_) { /* e'tiborsiz */ }
}

const state = {
  deviceId: null,
  token: loadToken(),
  googleClientId: "",
  customer: null,
  products: null,
  categories: [],
  activeCategory: "",
  search: "",
  cart: { items: [], total_amount: 0, total_quantity: 0 },
  cartTtlDays: 7,
  activeProduct: null,
  pendingAddProductId: null,
  afterLogin: null,
};

const el = (id) => document.getElementById(id);

document.getElementById("year").textContent = new Date().getFullYear();

/* Yordamchilar */

function getDeviceId() {
  let id = localStorage.getItem(DEVICE_KEY);
  if (!id) {
    id =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID().replace(/-/g, "")
        : `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
    localStorage.setItem(DEVICE_KEY, id);
  }
  return id;
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    data = null;
  }

  if (!res.ok) {
    const message = data && data.detail ? data.detail : `Server xatosi (${res.status})`;
    const error = new Error(typeof message === "string" ? message : "Xatolik yuz berdi.");
    error.status = res.status;
    // Sessiya tugagan yoki yaroqsiz: mijozni chiqarib yuboramiz, keyingi
    // "Savatga" bosilganda Google oynasi qayta ochiladi.
    if (res.status === 401 && state.token) endSession(false);
    throw error;
  }
  return data;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function formatPrice(value) {
  return Math.round(Number(value) || 0)
    .toLocaleString("uz-UZ")
    .replace(/[,\u00A0]/g, " ");
}

let toastTimer = null;
function showToast(message, isError = false) {
  const toast = el("toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function lockScroll(locked) {
  document.body.classList.toggle("locked", locked);
}

/* Google orqali kirish — "Savatga" tugmasi bosilganda, agar foydalanuvchi
   hali kirmagan bo'lsa ochiladi. Ism so'ralmaydi: Google tokeni serverda
   tekshiriladi (/api/auth/google), server o'z sessiya tokenini beradi. */

const GATE_DEFAULT_TEXT =
  "Mahsulotni savatga qo'shish uchun Google akkauntingiz bilan kiring. Ismingiz Gmail akkauntingizdan avtomatik olinadi — buyurtmangiz shu ism bilan qayd qilinadi, savatingiz esa istalgan qurilmada saqlanib turadi.";

/* opts.text -- oynadagi tushuntirish matni (masalan konstruktor uchun boshqacha),
   opts.onSuccess -- kirish (va ism kiritish) muvaffaqiyatli tugagach chaqiriladi. */
function openGate(pendingProductId = null, opts = {}) {
  state.pendingAddProductId = pendingProductId;
  state.afterLogin = typeof opts.onSuccess === "function" ? opts.onSuccess : null;
  const intro = el("gate").querySelector(".gate-card p:not(.gate-note)");
  if (intro) intro.textContent = opts.text || GATE_DEFAULT_TEXT;
  el("gateError").textContent = "";
  el("gate").classList.add("open");
  lockScroll(true);
  renderGoogleButton();
}

function closeGate() {
  el("gate").classList.remove("open");
  if (!document.querySelector(".modal-overlay.open") && !el("cartDrawer").classList.contains("open")) {
    lockScroll(false);
  }
}

el("gateCancel").addEventListener("click", () => {
  state.pendingAddProductId = null;
  state.afterLogin = null;
  closeGate();
});

function paintAvatar(node, customer) {
  const displayName = (customer && (customer.name || customer.email)) || "?";
  node.textContent = displayName.trim().charAt(0).toUpperCase();
  if (customer && customer.picture_url) {
    const img = new Image();
    img.alt = "";
    img.referrerPolicy = "no-referrer"; // Google rasmlari referersiz ochilganda ishonchliroq
    img.onload = () => { node.textContent = ""; node.appendChild(img); };
    img.src = customer.picture_url;
  }
}

function applyCustomer(customer) {
  state.customer = customer;
  const chip = el("userChip");
  const displayName = customer.name || customer.email || "?";
  el("userName").textContent = displayName;
  chip.title = `${displayName} — profil`;
  chip.setAttribute("aria-label", "Profil");
  paintAvatar(el("userInitial"), customer);
  chip.hidden = false;
  // Boshqa skriptlar (masalan konstruktor sahifasi) kirish holatini shu orqali biladi.
  document.dispatchEvent(new CustomEvent("lg:auth", { detail: customer }));
}

/* Boshqa skriptlar (masalan constructor.html) uchun kichik yordamchilar. */
function currentCustomer() { return state.customer; }
function isAuthChecked() { return !!state.authChecked; }

/* Sessiyani tugatish. `manual` = foydalanuvchi o'zi "chiqish" bosdi. */
function endSession(manual = true) {
  state.token = null;
  state.customer = null;
  state.cart = { items: [], total_amount: 0, total_quantity: 0 };
  saveToken(null);
  el("userChip").hidden = true;
  try { window.google?.accounts?.id?.disableAutoSelect(); } catch (_) { /* e'tiborsiz */ }
  closeProfile();
  closeNameModal();
  document.dispatchEvent(new CustomEvent("lg:auth", { detail: null }));
  renderCart();
  if (manual) {
    closeCart();
    showToast("Akkauntdan chiqdingiz.");
  } else {
    showToast("Sessiya tugadi. Qaytadan Google orqali kiring.", true);
  }
}

/* ---------- Akkaunt oynalari: ism so'rash va profil ----------
   Oynalar HTML'ga qo'lda yozilmaydi -- bu yerdan bir marta yaratiladi, shu
   sababli barcha sahifalarda (bosh sahifa, mahsulotlar, konstruktor...)
   bir xil ishlaydi. Stillar: style.css (.lg-overlay, .lg-card ...). */

function formatWait(seconds) {
  const total = Math.max(1, Math.round(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return m > 0 ? `${h} soat ${m} daqiqa` : `${h} soat`;
  return `${Math.max(1, m)} daqiqa`;
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (isNaN(d)) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
}

const NAME_MIN = 2;
const NAME_MAX = 60;
function validateNameClient(value) {
  const name = (value || "").replace(/\s+/g, " ").trim();
  if (name.length < NAME_MIN) return { error: "Ism kamida 2 ta belgidan iborat bo'lsin." };
  if (name.length > NAME_MAX) return { error: "Ism 60 ta belgidan oshmasin." };
  if (!/\p{L}/u.test(name)) return { error: "Ismda kamida bitta harf bo'lishi kerak." };
  if (!/^[\p{L}\p{N}\s'‘’ʻʼ´`.\-]+$/u.test(name)) {
    return { error: "Ismda faqat harflar, bo'sh joy, apostrof va tire bo'lishi mumkin." };
  }
  return { name };
}

const LOCK_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';

let accountUiBuilt = false;
function ensureAccountUI() {
  if (accountUiBuilt) return;
  accountUiBuilt = true;
  const wrap = document.createElement("div");
  wrap.innerHTML = `
  <div class="lg-overlay" id="nameModal" role="dialog" aria-modal="true" aria-labelledby="nameModalTitle">
    <form class="lg-card lg-center" id="nameForm" novalidate>
      <div class="lg-avatar lg-avatar-lg" id="nameAvatar"></div>
      <h2 id="nameModalTitle">Ismingizni kiriting</h2>
      <p class="lg-sub">Google akkaunt tanlandi: <strong id="nameEmail"></strong>.<br />Buyurtmalaringiz shu ism bilan qayd qilinadi.</p>
      <label class="lg-field">
        <span>Ismingiz</span>
        <input id="nameInput" type="text" maxlength="${NAME_MAX}" autocomplete="name" placeholder="Masalan: Ali Valiyev" />
      </label>
      <div class="lg-error" id="nameError" role="alert"></div>
      <button class="btn btn-primary btn-block" id="nameSubmit" type="submit">Davom etish</button>
      <p class="lg-hint">Ismni keyinroq profilingizdan o'zgartirishingiz mumkin. Email o'zgarmaydi.</p>
    </form>
  </div>

  <div class="lg-overlay" id="profileModal" role="dialog" aria-modal="true" aria-labelledby="profileTitle">
    <div class="lg-card lg-profile">
      <button class="lg-close" id="profileClose" type="button" aria-label="Yopish">✕</button>
      <div class="lg-profile-head">
        <div class="lg-avatar lg-avatar-lg" id="profileAvatar"></div>
        <div>
          <h2 id="profileTitle">Profil</h2>
          <p class="lg-sub" id="profileSince"></p>
        </div>
      </div>
      <form id="profileForm" novalidate>
        <label class="lg-field">
          <span>Ism</span>
          <input id="profileName" type="text" maxlength="${NAME_MAX}" autocomplete="name" />
        </label>
        <div class="lg-field lg-locked">
          <span>Email (Google akkaunt)</span>
          <div class="lg-locked-box">
            <input id="profileEmail" type="text" readonly tabindex="-1" aria-readonly="true" />
            ${LOCK_ICON}
          </div>
          <small>Email Google akkauntingizdan olinadi va o'zgartirilmaydi.</small>
        </div>
        <div class="lg-error" id="profileError" role="alert"></div>
        <button class="btn btn-primary btn-block" id="profileSave" type="submit" disabled>Saqlash</button>
      </form>
      <div class="lg-info">
        <div class="lg-info-row"><span>Konstruktor</span><strong id="profileConstructor">—</strong></div>
      </div>
      <div class="lg-logout" id="profileLogoutArea"></div>
    </div>
  </div>`;
  while (wrap.firstChild) document.body.appendChild(wrap.firstChild);

  /* Ism so'rash oynasi: yopib bo'lmaydi (Esc/tashqariga bosish ishlamaydi) —
     ism kiritilmaguncha davom etilmaydi. */
  el("nameForm").addEventListener("submit", onNameSubmit);
  el("nameInput").addEventListener("input", () => { el("nameError").textContent = ""; });

  /* Profil oynasi */
  el("profileClose").addEventListener("click", closeProfile);
  el("profileModal").addEventListener("click", (e) => { if (e.target === el("profileModal")) closeProfile(); });
  el("profileName").addEventListener("input", () => {
    el("profileError").textContent = "";
    updateProfileSaveState();
  });
  el("profileForm").addEventListener("submit", onProfileSubmit);
  renderLogoutArea(false);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && el("profileModal").classList.contains("open")) closeProfile();
  });
}

function overlayOpen(id) {
  ensureAccountUI();
  el(id).classList.add("open");
  lockScroll(true);
}
function overlayClose(id) {
  const node = el(id);
  if (!node || !node.classList.contains("open")) return;
  node.classList.remove("open");
  if (
    !document.querySelector(".modal-overlay.open, .lg-overlay.open") &&
    !el("cartDrawer").classList.contains("open") &&
    !el("gate").classList.contains("open")
  ) {
    lockScroll(false);
  }
}

/* --- Ism so'rash (Google akkaunt tanlangandan keyin) --- */

let nameModalResolve = null;
let nameModalPromise = null;

function askForName(customer) {
  if (nameModalPromise) return nameModalPromise;
  ensureAccountUI();
  paintAvatar(el("nameAvatar"), customer);
  el("nameEmail").textContent = customer.email || "";
  el("nameInput").value = customer.name || "";
  el("nameError").textContent = "";
  el("nameSubmit").disabled = false;
  nameModalPromise = new Promise((resolve) => { nameModalResolve = resolve; });
  overlayOpen("nameModal");
  setTimeout(() => { el("nameInput").focus(); el("nameInput").select(); }, 60);
  return nameModalPromise;
}

function finishNameModal(result) {
  overlayClose("nameModal");
  const resolve = nameModalResolve;
  nameModalResolve = null;
  nameModalPromise = null;
  if (resolve) resolve(result);
}

function closeNameModal() {
  if (nameModalPromise) finishNameModal(null); // sessiya tugagan
}

async function onNameSubmit(e) {
  e.preventDefault();
  const checked = validateNameClient(el("nameInput").value);
  if (checked.error) { el("nameError").textContent = checked.error; return; }
  const btn = el("nameSubmit");
  btn.disabled = true;
  try {
    const updated = await api("/auth/profile", { method: "PUT", body: JSON.stringify({ name: checked.name }) });
    applyCustomer(updated);
    finishNameModal(updated);
  } catch (err) {
    if (err.status === 401) return; // api() sessiyani tugatdi, endSession oynani yopdi
    el("nameError").textContent = err.message;
    btn.disabled = false;
  }
}

/* --- Profil oynasi --- */

function updateProfileSaveState() {
  const current = (state.customer && state.customer.name) || "";
  const typed = el("profileName").value.replace(/\s+/g, " ").trim();
  el("profileSave").disabled = !typed || typed === current;
}

function renderLogoutArea(confirming) {
  const area = el("profileLogoutArea");
  if (!confirming) {
    area.innerHTML = '<button class="btn btn-ghost btn-block" id="profileLogout" type="button">Akkauntdan chiqish</button>';
    el("profileLogout").addEventListener("click", () => renderLogoutArea(true));
    return;
  }
  area.innerHTML = `
    <p class="lg-confirm-text">Akkauntdan chiqasizmi? Savatingiz saqlanib qoladi — qayta kirganingizda tiklanadi.</p>
    <div class="lg-confirm-row">
      <button class="btn btn-ghost" id="profileLogoutNo" type="button">Bekor qilish</button>
      <button class="btn lg-btn-danger" id="profileLogoutYes" type="button">Ha, chiqish</button>
    </div>`;
  el("profileLogoutNo").addEventListener("click", () => renderLogoutArea(false));
  el("profileLogoutYes").addEventListener("click", () => endSession(true));
}

async function fillConstructorStatus() {
  const node = el("profileConstructor");
  node.textContent = "…";
  try {
    const limit = await api("/constructor/limit");
    node.textContent = limit.allowed
      ? "bugun foydalanish mumkin"
      : `yana ${formatWait(limit.retry_after_seconds)} dan so'ng`;
  } catch (_) {
    node.textContent = "—";
  }
}

function openProfile() {
  const customer = state.customer;
  if (!customer) return;
  ensureAccountUI();
  paintAvatar(el("profileAvatar"), customer);
  el("profileName").value = customer.name || "";
  el("profileEmail").value = customer.email || "";
  el("profileSince").textContent = `Ro'yxatdan o'tgan: ${formatDate(customer.created_at)}`;
  el("profileError").textContent = "";
  renderLogoutArea(false);
  updateProfileSaveState();
  overlayOpen("profileModal");
  fillConstructorStatus();
}

function closeProfile() {
  if (accountUiBuilt) overlayClose("profileModal");
}

async function onProfileSubmit(e) {
  e.preventDefault();
  const checked = validateNameClient(el("profileName").value);
  if (checked.error) { el("profileError").textContent = checked.error; return; }
  const btn = el("profileSave");
  btn.disabled = true;
  try {
    const updated = await api("/auth/profile", { method: "PUT", body: JSON.stringify({ name: checked.name }) });
    applyCustomer(updated);
    el("profileName").value = updated.name;
    updateProfileSaveState();
    showToast("Ism yangilandi.");
  } catch (err) {
    if (err.status === 401) return;
    el("profileError").textContent = err.message;
    updateProfileSaveState();
  }
}

el("userChip").addEventListener("click", openProfile);

let gsiScriptPromise = null;
let gsiInitialized = false;

function loadGoogleScript() {
  if (window.google && window.google.accounts && window.google.accounts.id) return Promise.resolve();
  if (gsiScriptPromise) return gsiScriptPromise;
  gsiScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      gsiScriptPromise = null; // keyingi urinishda qayta yuklansin
      reject(new Error("Google xizmatini yuklab bo'lmadi. Internetni tekshirib, qayta urinib ko'ring."));
    };
    document.head.appendChild(script);
  });
  return gsiScriptPromise;
}

async function renderGoogleButton() {
  const holder = el("googleBtn");
  const errorEl = el("gateError");
  holder.innerHTML = "";

  if (!state.googleClientId) {
    // /site javobi hali kelmagan bo'lishi mumkin — bir marta qayta so'raymiz.
    const site = await api("/site").catch(() => null);
    if (site && site.google_client_id) state.googleClientId = site.google_client_id;
  }
  if (!state.googleClientId) {
    errorEl.textContent = "Google orqali kirish hozircha sozlanmagan. Iltimos, keyinroq urinib ko'ring.";
    return;
  }

  try {
    await loadGoogleScript();
  } catch (err) {
    errorEl.textContent = err.message;
    return;
  }

  if (!gsiInitialized) {
    window.google.accounts.id.initialize({
      client_id: state.googleClientId,
      callback: onGoogleCredential,
      auto_select: false,
      cancel_on_tap_outside: true,
    });
    gsiInitialized = true;
  }
  const width = Math.max(200, Math.min(340, holder.clientWidth || 300));
  window.google.accounts.id.renderButton(holder, {
    type: "standard",
    theme: "outline",
    size: "large",
    text: "continue_with",
    shape: "pill",
    logo_alignment: "left",
    width,
  });
}

async function onGoogleCredential(response) {
  const errorEl = el("gateError");
  errorEl.textContent = "";
  if (!response || !response.credential) {
    errorEl.textContent = "Google javob bermadi. Qayta urinib ko'ring.";
    return;
  }
  el("googleBtn").classList.add("busy");
  try {
    const auth = await api("/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential: response.credential, device_id: state.deviceId }),
    });
    state.token = auth.access_token;
    saveToken(auth.access_token);
    applyCustomer(auth.customer);
    closeGate();

    // Google akkaunt tanlangach ism so'raladi (bir marta; keyin profildan
    // o'zgartiriladi). Ism kiritilmaguncha davom etilmaydi.
    // Ism Gmail (Google) akkauntidan avtomatik olinadi — alohida so'ralmaydi.
    const customer = auth.customer;
    const firstName = (customer.name || "").split(" ")[0];
    showToast(auth.is_new ? `Xush kelibsiz, ${firstName}!` : `Qaytganingiz bilan, ${firstName}!`);

    const pendingId = state.pendingAddProductId;
    const afterLogin = state.afterLogin;
    state.pendingAddProductId = null;
    state.afterLogin = null;
    if (pendingId) {
      await addToCart(pendingId);
    } else {
      await refreshCart();
    }
    if (afterLogin) {
      try { afterLogin(customer); } catch (_) { /* e'tiborsiz */ }
    }
  } catch (err) {
    errorEl.textContent = err.message;
  } finally {
    el("googleBtn").classList.remove("busy");
  }
}

/* Katalog */

function mediaHTML(product, index = 1) {
  const urls = (product.image_urls && product.image_urls.length ? product.image_urls : (product.image_url ? [product.image_url] : []));
  // Faqat birinchi qatordagi kartalarning birinchi rasmi darhol yuklanadi (LCP),
  // qolganlari va galereyaning keyingi kadrlari faqat ko'rinish oldidan yuklanadi.
  const eager = index <= 4;
  if (urls.length) return `<div class="product-gallery" data-gallery="${product.id}">${urls.map((u,i)=>`<img class="gallery-shot ${i===0?'active':''}" src="${MEDIA_BASE}${u}" alt="${escapeHtml(product.name)} — ${i+1}" loading="${eager && i===0 ? 'eager' : 'lazy'}" decoding="async" />`).join("")}<span class="gallery-count">${urls.length > 1 ? `1 / ${urls.length}` : ""}</span></div>`;
  return `<div class="no-image"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 15 5-5 4 4 4-4 5 5"/></svg></div>`;
}

function renderFilters() {
  // #filters faqat katalog bo'lgan sahifalarda (bosh sahifa, mahsulotlar)
  // mavjud. Boshqa sahifalarda (masalan konstruktor) bu element umuman
  // yo'q -- shuning uchun bu yerda to'xtaymiz, aks holda quyidagi
  // container.innerHTML sinishi butun init() ni (savatni tiklash,
  // kategoriya sonini ko'rsatish, scroll-reveal animatsiyalarini
  // ishga tushirish) yarim yo'lda to'xtatib qo'yar edi.
  const container = el("filters");
  if (!container) return;
  container.innerHTML = "";

  const make = (label, value) => {
    const btn = document.createElement("button");
    btn.className = "filter-pill" + (state.activeCategory === value ? " active" : "");
    btn.textContent = label;
    btn.addEventListener("click", () => {
      state.activeCategory = value;
      renderFilters();
      loadProducts();
    });
    container.appendChild(btn);
  };

  make("Barchasi", "");
  state.categories.forEach((c) => make(c.name, c.name));
}

function renderProducts() {
  // #productGrid faqat katalog bo'lgan sahifalarda mavjud (yuqoridagi
  // renderFilters() dagi izohga qarang -- xuddi shu sababdan bu yerda
  // ham to'xtaymiz).
  const grid = el("productGrid");
  if (!grid) return;

  if (state.products === null) {
    grid.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`;
    return;
  }

  if (state.products.length === 0) {
    grid.innerHTML = `<p class="state-msg">Bu bo'limda hozircha mahsulot yo'q. Boshqa kategoriyani tanlab ko'ring.</p>`;
    return;
  }

  grid.innerHTML = state.products
    .map(
      (p, i) => `
      <article class="product-card reveal" data-id="${p.id}">
        <div class="product-media" data-open="${p.id}">${mediaHTML(p, i)}</div>
        ${likeButtonHTML(p, "card")}
        <div class="product-body">
          <span class="product-tag">${escapeHtml(p.category)}</span>
          <h3 class="product-name" data-open="${p.id}">${escapeHtml(p.name)}</h3>
          <p class="product-desc">${escapeHtml(p.description || "")}</p>
          <div class="product-foot">
            <div class="product-price">${formatPrice(p.sale_price)}<span>so'm</span></div>
            <button class="btn btn-primary btn-sm" data-add="${p.id}">Savatga</button>
          </div>
          <button class="comment-btn" type="button" data-comments-open="${p.id}" data-comments-for="${p.id}" aria-label="Izohlar">${commentBtnHTML(p.comment_count)}</button>
        </div>
      </article>`
    )
    .join("");

  grid.querySelectorAll(".product-gallery").forEach((gallery) => {
    const shots = Array.from(gallery.querySelectorAll(".gallery-shot"));
    if (shots.length < 2) return;
    let current = 0;
    let timer = null;
    const advance = () => {
      if (!gallery.isConnected) { clearInterval(timer); return; }
      const next = (current + 1) % shots.length;
      shots[current].classList.remove("active");
      // Force the browser to commit the outgoing frame before activating next.
      void shots[next].offsetWidth;
      shots[next].classList.add("active");
      current = next;
      const count = gallery.querySelector(".gallery-count");
      if (count) count.textContent = `${current + 1} / ${shots.length}`;
    };
    const startSlideshow = () => {
      if (timer) return;
      gallery.classList.add("is-playing");
      advance(); // immediate visible response on hover/click
      timer = window.setInterval(advance, 2200);
    };
    const stopSlideshow = () => {
      clearInterval(timer); timer = null;
      gallery.classList.remove("is-playing");
    };
    gallery.addEventListener("mouseenter", startSlideshow);
    gallery.addEventListener("focusin", startSlideshow);
    gallery.addEventListener("click", (event) => {
      // Clicking the image begins cycling; card click still opens detail modal.
      startSlideshow();
    });
    gallery.addEventListener("mouseleave", stopSlideshow);
    gallery.addEventListener("focusout", (event) => {
      if (!gallery.contains(event.relatedTarget)) stopSlideshow();
    });
  });

  grid.querySelectorAll("[data-add]").forEach((btn) => {
    btn.addEventListener("click", () => addToCart(Number(btn.dataset.add)));
  });

  grid.querySelectorAll("[data-like]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleLike(Number(btn.dataset.like));
    });
  });

  grid.querySelectorAll("[data-comments-open]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const product = productById(Number(btn.dataset.commentsOpen));
      if (product) openComments(product, btn);
    });
  });

  grid.querySelectorAll("[data-open]").forEach((node) => {
    node.addEventListener("click", () => {
      const product = state.products.find((p) => p.id === Number(node.dataset.open));
      if (product) openProduct(product);
    });
  });

  observeReveal(grid.querySelectorAll(".reveal"));
}

/* Scroll bilan ochiladigan animatsiya — element ko'rinish maydoniga
   kirganda bir marotaba ravon paydo bo'ladi, keyin kuzatuv to'xtaydi. */
let revealObserver = null;
function observeReveal(nodes) {
  if (!("IntersectionObserver" in window) || !nodes || !nodes.length) {
    (nodes || []).forEach((n) => n.classList.add("in-view"));
    return;
  }
  if (!revealObserver) {
    revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
  }
  nodes.forEach((n) => revealObserver.observe(n));
}

function initScrollReveal() {
  const targets = document.querySelectorAll(
    ".service-card, .step, .news-card, .rule, .contact-card, .about-stat"
  );
  targets.forEach((t) => t.classList.add("reveal"));
  observeReveal(targets);
}

async function loadProducts() {
  state.products = null;
  renderProducts();

  const params = new URLSearchParams();
  if (state.activeCategory) params.set("category", state.activeCategory);
  if (state.search) params.set("search", state.search);
  const query = params.toString() ? `?${params.toString()}` : "";

  try {
    state.products = await api(`/products${query}`);
  } catch (err) {
    state.products = [];
    const grid = el("productGrid");
    if (grid) grid.innerHTML = `<p class="state-msg">Mahsulotlarni yuklab bo'lmadi. Aloqani tekshirib, sahifani yangilang.</p>`;
    return;
  }
  renderProducts();
  const statProducts = el("statProducts");
  if (statProducts) statProducts.textContent = state.products.length;
}

let searchTimer = null;
// "searchInput" faqat mahsulotlar ro'yxati bo'lgan sahifalarda bor
// (index/products/news/contact). Konstruktor kabi boshqa sahifalarda bu
// element yo'q -- shartsiz el("searchInput") chaqirilsa, elementi bo'lmagan
// sahifada xatolik berib, shu qatordan keyingi BUTUN main.js to'xtab qolardi
// (shu jumladan mobil menyu, savat va boshqa tugmalar ham ishlamay qolardi).
if (el("searchInput")) {
  el("searchInput").addEventListener("input", (e) => {
    const value = e.target.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = value;
      loadProducts();
    }, 300);
  });
}

/* Mahsulot oynasi */

function openProduct(product) {
  state.activeProduct = product;
  const urls = (product.image_urls && product.image_urls.length ? product.image_urls : (product.image_url ? [product.image_url] : []));
  const media = el("modalMedia");
  media.innerHTML = urls.length ? `
    <div class="detail-gallery" data-index="0">
      <button class="detail-arrow prev" type="button" aria-label="Oldingi rasm">‹</button>
      <img class="detail-main-image" src="${MEDIA_BASE}${urls[0]}" alt="${escapeHtml(product.name)}" />
      <button class="detail-arrow next" type="button" aria-label="Keyingi rasm">›</button>
      <button class="detail-zoom" type="button">⤢ Kattalashtirish</button>
      <span class="detail-counter">1 / ${urls.length}</span>
    </div>
    ${urls.length > 1 ? `<div class="detail-thumbs">${urls.map((u,i)=>`<button class="detail-thumb ${i===0?'active':''}" data-thumb="${i}" type="button"><img src="${MEDIA_BASE}${u}" alt="${escapeHtml(product.name)} ${i+1}" /></button>`).join("")}</div>` : ""}` : mediaHTML(product);
  const showIndex = (idx) => {
    const gallery = media.querySelector('.detail-gallery'); if (!gallery || !urls.length) return;
    idx = (idx + urls.length) % urls.length; gallery.dataset.index = idx;
    gallery.querySelector('.detail-main-image').src = MEDIA_BASE + urls[idx];
    gallery.querySelector('.detail-counter').textContent = `${idx+1} / ${urls.length}`;
    media.querySelectorAll('.detail-thumb').forEach((b,i)=>b.classList.toggle('active', i===idx));
  };
  media.querySelector('.prev')?.addEventListener('click', e=>{e.stopPropagation();showIndex(Number(media.querySelector('.detail-gallery').dataset.index)-1)});
  media.querySelector('.next')?.addEventListener('click', e=>{e.stopPropagation();showIndex(Number(media.querySelector('.detail-gallery').dataset.index)+1)});
  media.querySelectorAll('[data-thumb]').forEach(b=>b.addEventListener('click',()=>showIndex(Number(b.dataset.thumb))));
  const zoom = () => {
    const idx=Number(media.querySelector('.detail-gallery')?.dataset.index||0); if(!urls.length)return;
    let lb=document.getElementById('productLightbox');
    if(!lb){lb=document.createElement('div');lb.id='productLightbox';lb.className='product-lightbox';lb.innerHTML='<button class="lightbox-close" aria-label="Yopish">×</button><button class="lightbox-prev">‹</button><img alt="Mahsulot rasmi"><button class="lightbox-next">›</button><span class="lightbox-count"></span>';document.body.appendChild(lb);}
    let li=idx; const paint=()=>{lb.querySelector('img').src=MEDIA_BASE+urls[li];lb.querySelector('.lightbox-count').textContent=`${li+1} / ${urls.length}`;};
    lb.classList.add('open'); paint(); lb.querySelector('.lightbox-close').onclick=()=>lb.classList.remove('open');
    lb.querySelector('.lightbox-prev').onclick=()=>{li=(li+urls.length-1)%urls.length;paint()};lb.querySelector('.lightbox-next').onclick=()=>{li=(li+1)%urls.length;paint()};lb.onclick=e=>{if(e.target===lb)lb.classList.remove('open')};
  };
  media.querySelector('.detail-main-image')?.addEventListener('click',zoom);
  media.querySelector('.detail-zoom')?.addEventListener('click',zoom);
  el("modalCategory").textContent = product.category;
  el("modalName").textContent = product.name;
  el("modalDesc").textContent = product.description || "Tavsif kiritilmagan.";
  el("modalPrice").innerHTML = `${formatPrice(product.sale_price)}<span>so'm</span>`;
  openModal("productModal");
  openSocial(product);
}

el("modalAddBtn").addEventListener("click", () => {
  if (state.activeProduct) {
    addToCart(state.activeProduct.id);
    closeModal("productModal");
  }
});

/* ---------- Like (yurakcha) va izohlar ----------
   Faqat Google orqali kirganlar like bosa oladi va izoh yoza oladi; izohlarni
   hamma ko'radi. Izohda faqat ISM va matn chiqadi (email/rasm yo'q). Hamma
   matn DOMga faqat textContent orqali yoziladi -- HTML sifatida ishlamaydi.
   Limit: bitta akkaunt bitta mahsulotga 5 tagacha izoh, har biri 100 belgigacha
   (aniq qiymatlar serverdan keladi). */

const HEART_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7.5-4.6-9.6-9.3C1 8.4 2.9 5 6.2 5c2 0 3.2 1.1 3.8 2.1h4C14.6 6.1 15.8 5 17.8 5c3.3 0 5.2 3.4 3.8 6.7C19.5 16.4 12 21 12 21z" transform="translate(0 -.5)"/></svg>';

function likeButtonHTML(p, where) {
  const cls = where === "card" ? "like-btn like-card" : "like-btn like-big";
  return `<button class="${cls}${p.liked ? " liked" : ""}" type="button" data-like="${p.id}" data-like-where="${where}" aria-pressed="${p.liked ? "true" : "false"}" aria-label="${p.liked ? "Like'ni qaytarib olish" : "Yoqdi"}">${HEART_SVG}<span class="like-num">${p.like_count || 0}</span></button>`;
}

const CHAT_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';

/* Izoh tugmasi ichi: ikonka + matn + (izoh bo'lsa) soni. Faqat son qo'yiladi -- xavfsiz. */
function commentBtnHTML(n) {
  const count = Number(n) || 0;
  return `${CHAT_SVG}<span class="cb-label">${count > 0 ? "Izohlar" : "Izoh yozish"}</span>${count > 0 ? `<span class="cb-count">${count}</span>` : ""}`;
}

function productById(id) {
  return (state.products || []).find((p) => p.id === id) || null;
}

/* Kartadagi va oynadagi yurakcha/hisoblagichlarni state bilan moslaydi. */
function paintProductSocial(productId) {
  const p = productById(productId);
  if (!p) return;
  document.querySelectorAll(`[data-like="${productId}"]`).forEach((btn) => {
    btn.classList.toggle("liked", !!p.liked);
    btn.setAttribute("aria-pressed", p.liked ? "true" : "false");
    btn.setAttribute("aria-label", p.liked ? "Like'ni qaytarib olish" : "Yoqdi");
    const num = btn.querySelector(".like-num");
    if (num) num.textContent = p.like_count || 0;
  });
  document.querySelectorAll(`[data-comments-for="${productId}"]`).forEach((node) => {
    node.innerHTML = commentBtnHTML(p.comment_count);
  });
}

function requireLogin(text, onSuccess) {
  openGate(null, { text, onSuccess });
}

const likePending = new Set();
async function toggleLike(productId) {
  if (!state.customer) {
    requireLogin("Mahsulotga like bosish uchun Google akkauntingiz bilan kiring.", () => toggleLike(productId));
    return;
  }
  if (likePending.has(productId)) return;
  const p = productById(productId);
  if (!p) return;
  likePending.add(productId);
  try {
    const res = await api(`/products/${productId}/like`, { method: p.liked ? "DELETE" : "PUT" });
    p.liked = res.liked;
    p.like_count = res.like_count;
    paintProductSocial(productId);
  } catch (err) {
    showToast(err.message, true);
  } finally {
    likePending.delete(productId);
  }
}

function formatDateTime(iso) {
  if (!iso) return "";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (isNaN(d)) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ---------- Izohlar oynasi ----------
   Izohlar mahsulot oynasidan ALOHIDA, o'zining oynasida ochiladi (tovar
   kattalashib ketmaydi). Telefonda pastdan chiqadigan oyna, kompyuterda
   markazdagi oyna. Hamma matn DOMga faqat textContent orqali yoziladi --
   HTML sifatida ishlamaydi. Limitlar (5 ta izoh, 100 belgi, 3 ta tahrir)
   serverdan keladi. */

const SEND_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4z"/></svg>';

/* Admin tasdiqlash belgisi (rosetka + galochka). Statik, foydalanuvchi matni yo'q. */
const BADGE_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" d="M12.00 1.10 L13.81 2.88 L16.17 1.93 L17.17 4.27 L19.71 4.29 L19.73 6.83 L22.07 7.83 L21.12 10.19 L22.90 12.00 L21.12 13.81 L22.07 16.17 L19.73 17.17 L19.71 19.71 L17.17 19.73 L16.17 22.07 L13.81 21.12 L12.00 22.90 L10.19 21.12 L7.83 22.07 L6.83 19.73 L4.29 19.71 L4.27 17.17 L1.93 16.17 L2.88 13.81 L1.10 12.00 L2.88 10.19 L1.93 7.83 L4.27 6.83 L4.29 4.29 L6.83 4.27 L7.83 1.93 L10.19 2.88Z"/><path fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="m7.6 12.4 3 3 5.8-6.2"/></svg>';

const CM_PAGE = 20; // bir vaqtda chiqariladigan izohlar (uzun ro'yxat qotmasligi uchun)
const cm = { productId: null, productName: "", data: null, editingId: null, shown: CM_PAGE, draft: "", busy: false, opener: null };

/* Kuchsiz qurilmalarda (kam xotira/yadro) yoki "animatsiyani kamaytirish" yoqilgan bo'lsa
   oyna animatsiyasiz, yengil ishlaydi. */
(function markLiteDevice() {
  try {
    const weak =
      (navigator.deviceMemory && navigator.deviceMemory <= 2) ||
      (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2) ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    if (weak) document.documentElement.classList.add("lite");
  } catch (_) { /* e'tiborsiz */ }
})();

function safeAvatar(url) {
  try {
    const u = new URL(url);
    const h = u.hostname.toLowerCase();
    if (u.protocol !== "https:") return "";
    if (h === "googleusercontent.com" || h.endsWith(".googleusercontent.com") || h.endsWith(".ggpht.com")) return u.href;
  } catch (_) { /* yaroqsiz manzil */ }
  return "";
}

const AVATAR_COLORS = ["#2e86c8", "#12557f", "#d98a2b", "#3f9a68", "#7d5bc4", "#c4506a", "#3c6484"];

/* Profil rasmi; rasm bo'lmasa yoki yuklanmasa -- ism bosh harfi (rangli doira). */
function avatarEl(name, url) {
  const wrap = document.createElement("span");
  wrap.className = "cm-avatar";
  const label = String(name || "?").trim();
  let hash = 0;
  for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) | 0;
  wrap.style.background = AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
  wrap.textContent = (Array.from(label)[0] || "?").toUpperCase();
  const src = safeAvatar(url);
  if (src) {
    const img = document.createElement("img");
    img.alt = "";
    img.width = 40;
    img.height = 40;
    img.loading = "lazy";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => img.remove(), { once: true });
    img.src = src;
    wrap.appendChild(img);
  }
  return wrap;
}

function friendlyError(err) {
  return err && err.status ? err.message : "Internet bilan aloqa yo'q. Birozdan so'ng qayta urinib ko'ring.";
}

/* Mahsulot oynasida (kattalashgan ko'rinish) faqat yurakcha va "Izohlar" tugmasi bo'ladi;
   izohlarning o'zi alohida oynada ochiladi. */
function ensureSocialUI() {
  if (el("socialBox")) return;
  const body = document.querySelector("#productModal .modal-body");
  if (!body) return;
  const box = document.createElement("section");
  box.id = "socialBox";
  box.className = "social-box";
  box.innerHTML = `
    <div class="social-head">
      <span id="socialLikeHolder"></span>
      <button type="button" class="comment-btn" id="socialCommentBtn" data-comments-for=""></button>
    </div>`;
  body.appendChild(box);
}

function openSocial(product) {
  ensureSocialUI();
  if (!el("socialBox")) return;
  el("socialLikeHolder").innerHTML = likeButtonHTML(product, "modal");
  el("socialLikeHolder").querySelector("[data-like]").addEventListener("click", () => toggleLike(product.id));
  const btn = el("socialCommentBtn");
  btn.dataset.commentsFor = String(product.id);
  btn.innerHTML = commentBtnHTML(product.comment_count);
  btn.onclick = () => openComments(product, btn);
}

/* ----- Oynaning o'zi ----- */

let commentsFitRaf = 0;
function fitCommentsToViewport() {
  // Telefonda klaviatura ochilganda oyna va yozish maydoni klaviatura ostida qolmasligi uchun.
  const ov = el("commentsModal");
  const vv = window.visualViewport;
  if (!ov || !vv || !ov.classList.contains("open")) return;
  cancelAnimationFrame(commentsFitRaf);
  commentsFitRaf = requestAnimationFrame(() => {
    ov.style.top = `${vv.offsetTop}px`;
    ov.style.height = `${vv.height}px`;
    ov.style.bottom = "auto";
    ov.classList.toggle("kb", vv.height < window.innerHeight * 0.75);
  });
}

function ensureCommentsUI() {
  if (el("commentsModal")) return;
  const ov = document.createElement("div");
  ov.className = "modal-overlay comments-overlay";
  ov.id = "commentsModal";
  ov.setAttribute("role", "dialog");
  ov.setAttribute("aria-modal", "true");
  ov.setAttribute("aria-labelledby", "commentsTitle");
  ov.innerHTML = `
    <div class="comments-sheet" tabindex="-1">
      <div class="cm-handle" aria-hidden="true"></div>
      <header class="cm-head">
        <div class="cm-titles">
          <h3 id="commentsTitle">Izohlar</h3>
          <p class="cm-sub" id="commentsSub"></p>
        </div>
        <button class="cm-close" id="commentsClose" type="button" aria-label="Yopish">✕</button>
      </header>
      <div class="cm-body" id="commentsList" aria-live="polite"></div>
      <footer class="cm-foot" id="commentsForm"></footer>
    </div>`;
  document.body.appendChild(ov);
  ov.addEventListener("click", (e) => { if (e.target === ov) closeComments(); });
  el("commentsClose").addEventListener("click", closeComments);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", fitCommentsToViewport);
    window.visualViewport.addEventListener("scroll", fitCommentsToViewport);
  }
}

function closeComments() {
  const ov = el("commentsModal");
  if (!ov) return;
  closeModal("commentsModal");
  ov.style.top = ov.style.height = ov.style.bottom = "";
  ov.classList.remove("kb");
  cm.editingId = null;
  if (cm.opener && cm.opener.isConnected) { try { cm.opener.focus({ preventScroll: true }); } catch (_) { /* e'tiborsiz */ } }
  cm.opener = null;
}

function openComments(product, opener) {
  ensureCommentsUI();
  if (cm.productId !== product.id) cm.draft = "";
  cm.productId = product.id;
  cm.productName = product.name || "";
  cm.data = null;
  cm.editingId = null;
  cm.shown = CM_PAGE;
  cm.opener = opener || null;
  el("commentsTitle").textContent = "Izohlar";
  el("commentsSub").textContent = cm.productName;
  el("commentsForm").textContent = "";
  const list = el("commentsList");
  list.textContent = "";
  const loading = document.createElement("p");
  loading.className = "cm-empty-text";
  loading.textContent = "Yuklanmoqda…";
  list.appendChild(loading);
  openModal("commentsModal");
  fitCommentsToViewport();
  const sheet = document.querySelector("#commentsModal .comments-sheet");
  if (sheet) sheet.focus({ preventScroll: true });
  loadComments(product.id, { top: true });
}

async function loadComments(productId, opts = {}) {
  try {
    const data = await api(`/products/${productId}/social`);
    if (cm.productId !== productId) return; // foydalanuvchi boshqa mahsulotni ochib bo'ldi
    cm.data = data;
    const p = productById(productId);
    if (p) {
      p.like_count = data.like_count;
      p.liked = data.liked;
      p.comment_count = data.comment_count;
      paintProductSocial(productId);
    }
    renderComments();
    if (opts.top) el("commentsList").scrollTop = 0;
  } catch (err) {
    if (cm.productId !== productId) return;
    const list = el("commentsList");
    list.textContent = "";
    const box = document.createElement("div");
    box.className = "cm-empty";
    const text = document.createElement("p");
    text.className = "cm-empty-text";
    text.textContent = "Izohlarni yuklab bo'lmadi.";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn btn-ghost btn-sm";
    retry.textContent = "Qayta urinish";
    retry.addEventListener("click", () => {
      list.textContent = "";
      const again = document.createElement("p");
      again.className = "cm-empty-text";
      again.textContent = "Yuklanmoqda…";
      list.appendChild(again);
      loadComments(productId, { top: true });
    });
    box.append(text, retry);
    list.appendChild(box);
  }
}

function renderComments() {
  const data = cm.data;
  if (!data) return;
  el("commentsTitle").textContent = data.comment_count > 0 ? `Izohlar (${data.comment_count})` : "Izohlar";
  renderComposer();

  const list = el("commentsList");
  const keepTop = list.scrollTop;
  list.textContent = "";

  if (!data.comments.length) {
    const empty = document.createElement("div");
    empty.className = "cm-empty";
    const icon = document.createElement("span");
    icon.className = "cm-empty-icon";
    icon.innerHTML = CHAT_SVG;
    const text = document.createElement("p");
    text.className = "cm-empty-text";
    text.textContent = "Hozircha izoh yo'q. Birinchi bo'lib fikringizni yozing!";
    empty.append(icon, text);
    list.appendChild(empty);
    return;
  }

  const frag = document.createDocumentFragment();
  data.comments.slice(0, cm.shown).forEach((c) => frag.appendChild(buildComment(c)));
  const rest = data.comments.length - cm.shown;
  if (rest > 0) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "cm-more";
    more.textContent = `Yana ${Math.min(rest, CM_PAGE)} ta izohni ko'rsatish`;
    more.addEventListener("click", () => { cm.shown += CM_PAGE; renderComments(); });
    frag.appendChild(more);
  }
  list.appendChild(frag);
  list.scrollTop = keepTop;
}

function buildComment(c) {
  const row = document.createElement("article");
  row.className = "cm-item" + (c.is_mine ? " mine" : "") + (c.is_admin ? " admin" : "");
  row.appendChild(avatarEl(c.name, c.avatar));

  const main = document.createElement("div");
  main.className = "cm-main";

  const top = document.createElement("div");
  top.className = "cm-top";
  const name = document.createElement("span");
  name.className = "cm-name";
  name.textContent = c.name;
  top.appendChild(name);
  if (c.is_admin) {
    const badge = document.createElement("span");
    badge.className = "cm-admin";
    badge.title = "Admin — saytning tasdiqlangan vakili";
    const icon = document.createElement("span");
    icon.className = "cm-badge";
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", "Admin");
    icon.innerHTML = BADGE_SVG;
    const tag = document.createElement("span");
    tag.className = "cm-admin-tag";
    tag.textContent = "Admin";
    badge.append(icon, tag);
    top.appendChild(badge);
  }
  if (c.is_mine) {
    const you = document.createElement("span");
    you.className = "cm-you";
    you.textContent = "siz";
    top.appendChild(you);
  }
  main.appendChild(top);

  const time = document.createElement("div");
  time.className = "cm-time";
  time.textContent = formatDateTime(c.created_at) + (c.edited ? " · tahrirlangan" : "");
  main.appendChild(time);

  if (cm.editingId === c.id) {
    main.appendChild(buildCommentEditor(c));
  } else {
    const text = document.createElement("p");
    text.className = "cm-text";
    text.textContent = c.body;
    main.appendChild(text);

    if (c.is_mine) {
      const actions = document.createElement("div");
      actions.className = "cm-actions";
      if (c.edits_left > 0) {
        const edit = document.createElement("button");
        edit.type = "button";
        edit.textContent = `Tahrirlash (${c.edits_left} ta qoldi)`;
        edit.addEventListener("click", () => { cm.editingId = c.id; renderComments(); });
        actions.appendChild(edit);
      } else {
        const done = document.createElement("span");
        done.className = "cm-limit";
        done.textContent = "Tahrir limiti tugagan";
        actions.appendChild(done);
      }
      const del = document.createElement("button");
      del.type = "button";
      del.className = "danger";
      del.textContent = "O'chirish";
      del.addEventListener("click", () => deleteComment(c.id));
      actions.appendChild(del);
      main.appendChild(actions);
    }
  }
  row.appendChild(main);
  return row;
}

function buildCommentEditor(comment) {
  const max = cm.data.comment_max_length;
  const wrap = document.createElement("div");
  wrap.className = "cm-editor";

  const input = document.createElement("textarea");
  input.rows = 2;
  input.maxLength = max;
  input.value = comment.body;
  input.setAttribute("aria-label", "Izohni tahrirlash");

  const hint = document.createElement("div");
  hint.className = "cm-hint";
  const counter = () => { hint.textContent = `${input.value.length}/${max} · saqlasangiz 1 ta tahrir sarflanadi, ${comment.edits_left} tadan ${comment.edits_left - 1} ta qoladi`; };
  counter();

  const err = document.createElement("div");
  err.className = "cm-error";
  err.setAttribute("role", "alert");

  input.addEventListener("input", () => { counter(); err.textContent = ""; });

  const row = document.createElement("div");
  row.className = "cm-actions cm-actions-end";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Bekor qilish";
  cancel.addEventListener("click", () => { cm.editingId = null; renderComments(); });
  const save = document.createElement("button");
  save.type = "button";
  save.className = "primary";
  save.textContent = "Saqlash";
  save.addEventListener("click", async () => {
    const text = input.value.trim();
    if (!text) { err.textContent = "Izoh bo'sh bo'lmasin."; return; }
    if (text === comment.body) { cm.editingId = null; renderComments(); return; } // o'zgarmagan -- tahrir sarflanmaydi
    if (cm.busy) return;
    cm.busy = true;
    save.disabled = true;
    try {
      await api(`/comments/${comment.id}`, { method: "PUT", body: JSON.stringify({ body: text }) });
      cm.editingId = null;
      await loadComments(cm.productId);
      showToast("Izoh yangilandi.");
    } catch (e) {
      if (e.status === 401) return;
      err.textContent = friendlyError(e);
      save.disabled = false;
    } finally {
      cm.busy = false;
    }
  });
  row.append(cancel, save);

  wrap.append(input, hint, err, row);
  setTimeout(() => { try { input.focus({ preventScroll: true }); } catch (_) { /* e'tiborsiz */ } }, 30);
  return wrap;
}

/* Pastdagi yozish joyi: kirmagan bo'lsa -- tushunarli "kirish" tugmasi; limit tugagan bo'lsa -- izoh; aks holda forma. */
function renderComposer() {
  const holder = el("commentsForm");
  const data = cm.data;
  holder.textContent = "";

  if (!state.customer) {
    const info = document.createElement("p");
    info.className = "cm-hint";
    info.textContent = "Izohlarni hamma o'qiy oladi. Izoh yozish uchun Google akkauntingiz bilan kiring.";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary btn-block";
    btn.textContent = "Google orqali kirish";
    btn.addEventListener("click", () => {
      requireLogin("Izoh yozish uchun Google akkauntingiz bilan kiring.", () => {
        if (cm.productId) loadComments(cm.productId);
      });
    });
    holder.append(info, btn);
    return;
  }

  const max = data.comment_max_length;
  const left = Math.max(0, data.comment_limit - data.my_comment_count);
  if (left === 0) {
    const full = document.createElement("p");
    full.className = "cm-hint cm-full";
    full.textContent = `Siz bu mahsulotga ${data.comment_limit} ta izoh yozib bo'ldingiz. Yangisini yozish uchun avval eskisini o'chiring.`;
    holder.appendChild(full);
    return;
  }

  const form = document.createElement("form");
  form.className = "cm-form";
  form.noValidate = true;

  const line = document.createElement("div");
  line.className = "cm-compose";
  line.appendChild(avatarEl(state.customer.name, state.customer.picture_url));

  const input = document.createElement("textarea");
  input.rows = 1;
  input.maxLength = max;
  input.value = cm.draft || "";
  input.placeholder = "Fikringizni yozing…";
  input.setAttribute("aria-label", "Izoh matni");
  input.setAttribute("enterkeyhint", "send");
  input.autocomplete = "off";

  const send = document.createElement("button");
  send.type = "submit";
  send.className = "cm-send";
  send.setAttribute("aria-label", "Yuborish");
  send.innerHTML = SEND_SVG;

  line.append(input, send);

  const err = document.createElement("div");
  err.className = "cm-error";
  err.setAttribute("role", "alert");

  const hint = document.createElement("div");
  hint.className = "cm-hint cm-hint-row";
  const count = document.createElement("span");
  const note = document.createElement("span");
  note.textContent = `Yana ${left} ta izoh yozishingiz mumkin`;
  hint.append(count, note);

  const privacy = document.createElement("p");
  privacy.className = "cm-hint cm-privacy";
  privacy.textContent = "Izohda ismingiz va Google profil rasmingiz ko'rinadi. Email ko'rinmaydi.";

  const grow = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
  };
  const paint = () => { count.textContent = `${input.value.length}/${max}`; };
  paint();
  input.addEventListener("input", () => { cm.draft = input.value; paint(); grow(); err.textContent = ""; });
  input.addEventListener("keydown", (e) => {
    // Enter -- yuborish (Shift+Enter ham bir qatorga aylanadi: server qatorlarni bo'shliqqa almashtiradi).
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); if (form.requestSubmit) form.requestSubmit(); else send.click(); }
  });

  form.append(line, err, hint, privacy);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) { err.textContent = "Izoh bo'sh bo'lmasin."; return; }
    if (cm.busy) return;
    cm.busy = true;
    send.disabled = true;
    try {
      await api(`/products/${cm.productId}/comments`, { method: "POST", body: JSON.stringify({ body: text }) });
      cm.draft = "";
      cm.shown = CM_PAGE;
      await loadComments(cm.productId, { top: true });
      showToast("Izoh qo'shildi.");
    } catch (e2) {
      if (e2.status === 401) return;
      err.textContent = friendlyError(e2);
    } finally {
      cm.busy = false;
      send.disabled = false;
    }
  });

  holder.appendChild(form);
  grow();
}

async function deleteComment(commentId) {
  if (!(await lgConfirm({ tone: "danger", title: "Izohni o'chirish", message: "Izohingiz hamma uchun o'chiriladi.", confirmText: "Ha, o'chirish" }))) return;
  const productId = cm.productId;
  try {
    await api(`/comments/${commentId}`, { method: "DELETE" });
    if (cm.productId === productId) await loadComments(productId);
    showToast("Izoh o'chirildi.");
  } catch (err) {
    if (err.status === 401) return;
    showToast(friendlyError(err), true);
  }
}

/* Kirish/chiqish holati o'zgarganda: yurakchalar (kim like bosgani) va izoh
   formasi yangilanadi. Mahsulotlar skeletsiz, jimgina qayta o'qiladi. */
let socialUserId = null;
async function refreshProductSocial() {
  if (!state.products || !state.products.length) return;
  const params = new URLSearchParams();
  if (state.activeCategory) params.set("category", state.activeCategory);
  if (state.search) params.set("search", state.search);
  const query = params.toString() ? `?${params.toString()}` : "";
  try {
    const fresh = await api(`/products${query}`);
    fresh.forEach((f) => {
      const p = productById(f.id);
      if (!p) return;
      p.like_count = f.like_count; p.comment_count = f.comment_count; p.liked = f.liked;
      paintProductSocial(p.id);
    });
  } catch (_) { /* e'tiborsiz */ }
}

document.addEventListener("lg:auth", (e) => {
  const id = e.detail ? e.detail.id : null;
  if (id === socialUserId) return; // faqat ism o'zgargan -- hech narsa qilish shart emas
  socialUserId = id;
  if (!id) {
    (state.products || []).forEach((p) => { p.liked = false; paintProductSocial(p.id); });
    if (cm.data) { cm.data.liked = false; cm.data.my_comment_count = 0; cm.data.comments.forEach((c) => { c.is_mine = false; c.edits_left = 0; }); cm.editingId = null; renderComments(); }
    return;
  }
  refreshProductSocial();
  if (el("commentsModal") && el("commentsModal").classList.contains("open") && cm.productId) loadComments(cm.productId);
});

/* Savat */

function renderCart() {
  const body = el("cartBody");
  const { items } = state.cart;

  el("cartTotal").textContent = `${formatPrice(state.cart.total_amount)} so'm`;

  const count = el("cartCount");
  count.textContent = state.cart.total_quantity;
  count.hidden = state.cart.total_quantity === 0;

  el("checkoutBtn").disabled = items.length === 0;
  el("clearCartBtn").disabled = items.length === 0;

  if (items.length === 0) {
    body.innerHTML = `<p class="drawer-empty">Savat bo'sh.<br />Katalogdan mahsulot tanlab, "Savatga" tugmasini bosing.</p>`;
    return;
  }

  body.innerHTML = items
    .map(
      (item) => `
      <div class="cart-row" data-id="${item.id}">
        ${
          item.image_url
            ? `<img class="cart-thumb" src="${MEDIA_BASE}${item.image_url}" alt="" loading="lazy" decoding="async" />`
            : `<div class="cart-thumb"></div>`
        }
        <div class="cart-info">
          <h4>${escapeHtml(item.name)}</h4>
          <p class="meta">${formatPrice(item.unit_price)} so'm · savatda yana ${item.days_left} kun turadi</p>
          <div class="cart-controls">
            <div class="qty">
              <button data-minus="${item.id}" aria-label="Kamaytirish">−</button>
              <span>${item.quantity}</span>
              <button data-plus="${item.id}" aria-label="Ko'paytirish">+</button>
            </div>
            <div class="cart-line-total">${formatPrice(item.line_total)} so'm</div>
          </div>
          <button class="link-danger" data-remove="${item.id}" style="margin-top:8px;">O'chirish</button>
        </div>
      </div>`
    )
    .join("");

  body.querySelectorAll("[data-plus]").forEach((b) =>
    b.addEventListener("click", () => changeQuantity(Number(b.dataset.plus), 1))
  );
  body.querySelectorAll("[data-minus]").forEach((b) =>
    b.addEventListener("click", () => changeQuantity(Number(b.dataset.minus), -1))
  );
  body.querySelectorAll("[data-remove]").forEach((b) =>
    b.addEventListener("click", () => removeItem(Number(b.dataset.remove)))
  );
}

async function refreshCart() {
  if (!state.customer) return;
  try {
    state.cart = await api("/cart");
    state.cartTtlDays = state.cart.cart_ttl_days;
    renderCart();
    if (state.cart.removed_expired > 0) {
      showToast(
        `${state.cart.removed_expired} ta mahsulot 7 kunlik muddati tugagani uchun savatdan chiqarildi.`
      );
    }
  } catch (err) {
    // 401 bo'lsa api() sessiyani o'zi tugatadi; boshqa xatolarda savat
    // avvalgi holatida qoladi.
  }
}

async function addToCart(productId) {
  if (!state.customer) {
    openGate(productId);
    return;
  }
  try {
    state.cart = await api("/cart", {
      method: "POST",
      body: JSON.stringify({ product_id: productId, quantity: 1 }),
    });
    renderCart();
    showToast(`Savatga qo'shildi. ${state.cartTtlDays} kun davomida saqlanadi.`);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function changeQuantity(itemId, delta) {
  const item = state.cart.items.find((i) => i.id === itemId);
  if (!item) return;

  const next = item.quantity + delta;
  if (next < 1) {
    removeItem(itemId);
    return;
  }

  try {
    state.cart = await api(`/cart/item/${itemId}`, {
      method: "PUT",
      body: JSON.stringify({ quantity: next }),
    });
    renderCart();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function removeItem(itemId) {
  try {
    state.cart = await api(`/cart/item/${itemId}`, { method: "DELETE" });
    renderCart();
    showToast("Savatdan o'chirildi.");
  } catch (err) {
    showToast(err.message, true);
  }
}

el("clearCartBtn").addEventListener("click", async () => {
  if (!(await lgConfirm({ tone: "danger", title: "Savatni bo'shatish", message: "Savatdagi hamma narsa o'chiriladi.", confirmText: "Ha, bo'shatish" }))) return;
  try {
    state.cart = await api("/cart", { method: "DELETE" });
    renderCart();
    showToast("Savat bo'shatildi.");
  } catch (err) {
    showToast(err.message, true);
  }
});

function openCart() {
  el("cartDrawer").classList.add("open");
  el("drawerOverlay").classList.add("open");
  lockScroll(true);
  if (state.customer) {
    refreshCart();
  } else {
    // Hali kirilmagan — savat bo'sh; Google oynasi faqat "Savatga" bosilganda chiqadi.
    state.cart = { items: [], total_amount: 0, total_quantity: 0 };
    renderCart();
  }
}

function closeCart() {
  el("cartDrawer").classList.remove("open");
  el("drawerOverlay").classList.remove("open");
  lockScroll(false);
}

el("cartBtn").addEventListener("click", openCart);
el("cartCloseBtn").addEventListener("click", closeCart);
el("drawerOverlay").addEventListener("click", closeCart);

/* Mobil menyu — main-nav 900px dan tor ekranda yashirilgani uchun kerak */

function openMobileNav() {
  el("mobileNav").classList.add("open");
  el("mobileNavOverlay").classList.add("open");
  el("menuToggle").setAttribute("aria-expanded", "true");
  lockScroll(true);
}

function closeMobileNav() {
  el("mobileNav").classList.remove("open");
  el("mobileNavOverlay").classList.remove("open");
  el("menuToggle").setAttribute("aria-expanded", "false");
  if (!document.querySelector(".modal-overlay.open") && !el("cartDrawer").classList.contains("open")) {
    lockScroll(false);
  }
}

el("menuToggle").addEventListener("click", () => {
  const isOpen = el("mobileNav").classList.contains("open");
  isOpen ? closeMobileNav() : openMobileNav();
});
el("mobileNavClose").addEventListener("click", closeMobileNav);
el("mobileNavOverlay").addEventListener("click", closeMobileNav);
document.querySelectorAll(".mobile-nav a").forEach((a) => {
  a.addEventListener("click", closeMobileNav);
  if (a.pathname === window.location.pathname) a.classList.add("active");
});
document.querySelectorAll(".main-nav a").forEach((a) => {
  if (a.pathname === window.location.pathname) a.classList.add("active");
});

/* Rasmiylashtirish — Telegram faqat shu yerda ko'rsatiladi */

el("checkoutBtn").addEventListener("click", async () => {
  const btn = el("checkoutBtn");
  btn.disabled = true;
  btn.textContent = "Rasmiylashtirilmoqda...";

  try {
    const result = await api("/checkout", { method: "POST" });

    el("orderCode").textContent = result.order_code;
    el("checkoutText").textContent =
      `${result.customer_name} nomiga ${formatPrice(result.total_amount)} so'mlik buyurtma yozildi. ` +
      `Quyidagi tugma sotuvchining Telegramini tayyor xabar bilan ochadi.`;
    el("orderPreview").textContent = result.message_text;
    el("telegramBtn").href = result.telegram_url;

    closeCart();
    await refreshCart();
    openModal("checkoutModal");
  } catch (err) {
    showToast(err.message, true);
  } finally {
    btn.textContent = "Rasmiylashtirish";
    btn.disabled = state.cart.items.length === 0;
  }
});

/* Modal boshqaruvi */

function openModal(id) {
  el(id).classList.add("open");
  lockScroll(true);
}

function closeModal(id) {
  el(id).classList.remove("open");
  if (!document.querySelector(".modal-overlay.open") && !el("cartDrawer").classList.contains("open")) {
    lockScroll(false);
  }
}

[
  ["productModalClose", "productModal"],
  ["checkoutModalClose", "checkoutModal"],
].forEach(([btnId, modalId]) => {
  el(btnId).addEventListener("click", () => closeModal(modalId));
});

document.querySelectorAll(".modal-overlay").forEach((overlay) => {
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal(overlay.id);
  });
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  document.querySelectorAll(".modal-overlay.open").forEach((m) => closeModal(m.id));
  if (el("gate").classList.contains("open")) {
    state.pendingAddProductId = null;
    state.afterLogin = null;
    closeGate();
  }
  closeCart();
  closeMobileNav();
});

/* Ishga tushirish */

async function init() {
  state.deviceId = getDeviceId();

  // Sayt analitikasi: bitta qurilma bir kunda faqat bitta marta hisoblanadi.
  // Natija kutilmaydi va xato bo'lsa ham sayt ishlashiga ta'sir qilmaydi.
  api("/visit", {
    method: "POST",
    body: JSON.stringify({ device_id: state.deviceId }),
  }).catch(() => {});

  // Tezlik uchun: sayt sozlamalari, mijoz, kategoriyalar va mahsulotlar
  // ketma-ket emas, BIR VAQTDA so'raladi — bu birinchi ko'rinishgacha
  // bo'lgan vaqtni sezilarli qisqartiradi, ayniqsa sekin mobil tarmoqda.
  const [siteResult, categoriesResult] = await Promise.all([
    api("/site").catch(() => null),
    api("/categories").catch(() => []),
    loadProducts(),
  ]);

  if (siteResult) {
    state.cartTtlDays = siteResult.cart_ttl_days;
    state.googleClientId = siteResult.google_client_id || "";
    el("statCartDays").textContent = siteResult.cart_ttl_days;
    if (siteResult.site_title) document.title = `${siteResult.site_title} — rasmli oynalar`;
  }

  // Sayt birinchi ochilganda hech narsa so'ralmaydi. Agar foydalanuvchi oldin
  // Google orqali kirgan bo'lsa, saqlangan sessiya tekshiriladi va savati
  // tiklanadi (token yaroqsiz bo'lsa api() uni o'zi tozalaydi).
  if (state.token) {
    try {
      const me = await api("/auth/me");
      applyCustomer(me);
      refreshCart();
    } catch (_) { /* sessiya yaroqsiz yoki tarmoq xatosi — mehmon sifatida davom etadi */ }
  }

  // Kirish holati aniq bo'ldi (kirgan yoki mehmon) -- sahifalar shundan keyin
  // "Google bilan kiring" kabi xabarlarni ko'rsatadi (yolg'on miltillashsiz).
  state.authChecked = true;
  document.dispatchEvent(new CustomEvent("lg:ready"));

  state.categories = categoriesResult || [];
  renderFilters();
  if (categoriesResult) el("statCategories").textContent = categoriesResult.length;

  initScrollReveal();
}

init();
