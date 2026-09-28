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
        <div class="product-body">
          <span class="product-tag">${escapeHtml(p.category)}</span>
          <h3 class="product-name" data-open="${p.id}">${escapeHtml(p.name)}</h3>
          <p class="product-desc">${escapeHtml(p.description || "")}</p>
          <div class="product-foot">
            <div class="product-price">${formatPrice(p.sale_price)}<span>so'm</span></div>
            <button class="btn btn-primary btn-sm" data-add="${p.id}">Savatga</button>
          </div>
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
}

el("modalAddBtn").addEventListener("click", () => {
  if (state.activeProduct) {
    addToCart(state.activeProduct.id);
    closeModal("productModal");
  }
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
