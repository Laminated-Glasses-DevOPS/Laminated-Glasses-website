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

const state = {
  deviceId: null,
  customer: null,
  products: null,
  categories: [],
  activeCategory: "",
  search: "",
  cart: { items: [], total_amount: 0, total_quantity: 0 },
  cartTtlDays: 7,
  activeProduct: null,
  pendingAddProductId: null,
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
      ...(options.body ? { "Content-Type": "application/json" } : {}),
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

/* Ismni so'rash — endi saytga kirganda EMAS, balki foydalanuvchi birinchi
   marta "Savatga" tugmasini bosganda, va faqat BIR MAROTABA ochiladi.
   Ism qayd qilingach, uni o'zgartirish imkoni berilmaydi. */

function openGate(pendingProductId = null) {
  state.pendingAddProductId = pendingProductId;
  el("gate").classList.add("open");
  lockScroll(true);
  setTimeout(() => el("gateName").focus(), 120);
}

function closeGate() {
  el("gate").classList.remove("open");
  if (!document.querySelector(".modal-overlay.open") && !el("cartDrawer").classList.contains("open")) {
    lockScroll(false);
  }
}

function applyCustomer(customer) {
  state.customer = customer;
  el("userName").textContent = customer.name;
  el("userInitial").textContent = customer.name.trim().charAt(0).toUpperCase();
  el("userChip").title = customer.name;
}

el("gateForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = el("gateName");
  const errorEl = el("gateError");
  const name = input.value.trim();

  if (name.length < 2) {
    errorEl.textContent = "Ismingizni to'liqroq yozing (kamida 2 ta harf).";
    input.focus();
    return;
  }

  errorEl.textContent = "";
  const btn = el("gateBtn");
  btn.disabled = true;
  btn.textContent = "Davom etilmoqda...";

  try {
    const customer = await api("/customer", {
      method: "POST",
      body: JSON.stringify({ device_id: state.deviceId, name }),
    });
    applyCustomer(customer);
    closeGate();
    showToast(`Xush kelibsiz, ${customer.name}!`);

    const pendingId = state.pendingAddProductId;
    state.pendingAddProductId = null;
    if (pendingId) {
      await addToCart(pendingId);
    } else {
      await refreshCart();
    }
  } catch (err) {
    errorEl.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Davom etish";
  }
});

/* Katalog */

function mediaHTML(product) {
  const urls = (product.image_urls && product.image_urls.length ? product.image_urls : (product.image_url ? [product.image_url] : []));
  if (urls.length) return `<div class="product-gallery" data-gallery="${product.id}">${urls.map((u,i)=>`<img class="gallery-shot ${i===0?'active':''}" src="${MEDIA_BASE}${u}" alt="${escapeHtml(product.name)} — ${i+1}" loading="eager" />`).join("")}<span class="gallery-count">${urls.length > 1 ? `1 / ${urls.length}` : ""}</span></div>`;
  return `<div class="no-image"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 15 5-5 4 4 4-4 5 5"/></svg></div>`;
}

function renderFilters() {
  const container = el("filters");
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
  const grid = el("productGrid");

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
      (p) => `
      <article class="product-card" data-id="${p.id}">
        <div class="product-media" data-open="${p.id}">${mediaHTML(p)}</div>
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
    el("productGrid").innerHTML = `<p class="state-msg">Mahsulotlarni yuklab bo'lmadi. Aloqani tekshirib, sahifani yangilang.</p>`;
    return;
  }
  renderProducts();
  el("statProducts").textContent = state.products.length;
}

let searchTimer = null;
el("searchInput").addEventListener("input", (e) => {
  const value = e.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.search = value;
    loadProducts();
  }, 300);
});

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
            ? `<img class="cart-thumb" src="${MEDIA_BASE}${item.image_url}" alt="" />`
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
    state.cart = await api(`/cart/${state.deviceId}`);
    state.cartTtlDays = state.cart.cart_ttl_days;
    renderCart();
    if (state.cart.removed_expired > 0) {
      showToast(
        `${state.cart.removed_expired} ta mahsulot 7 kunlik muddati tugagani uchun savatdan chiqarildi.`
      );
    }
  } catch (err) {
    if (err.status === 404) {
      state.customer = null;
    }
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
      body: JSON.stringify({ device_id: state.deviceId, product_id: productId, quantity: 1 }),
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
      body: JSON.stringify({ device_id: state.deviceId, quantity: next }),
    });
    renderCart();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function removeItem(itemId) {
  try {
    state.cart = await api(
      `/cart/item/${itemId}?device_id=${encodeURIComponent(state.deviceId)}`,
      { method: "DELETE" }
    );
    renderCart();
    showToast("Savatdan o'chirildi.");
  } catch (err) {
    showToast(err.message, true);
  }
}

el("clearCartBtn").addEventListener("click", async () => {
  if (!confirm("Savatdagi hamma narsa o'chirilsinmi?")) return;
  try {
    state.cart = await api(`/cart/${state.deviceId}`, { method: "DELETE" });
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
    // Hali ism kiritilmagan — savat hali bo'sh, ism so'ralmaydi.
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

/* Rasmiylashtirish — Telegram faqat shu yerda ko'rsatiladi */

el("checkoutBtn").addEventListener("click", async () => {
  const btn = el("checkoutBtn");
  btn.disabled = true;
  btn.textContent = "Rasmiylashtirilmoqda...";

  try {
    const result = await api("/checkout", {
      method: "POST",
      body: JSON.stringify({ device_id: state.deviceId }),
    });

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
  closeCart();
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

  try {
    const site = await api("/site");
    state.cartTtlDays = site.cart_ttl_days;
    el("statCartDays").textContent = site.cart_ttl_days;
    if (site.site_title) document.title = `${site.site_title} — rasmli oynalar`;
  } catch (_) {
    // Sayt sozlamalari yuklanmasa ham katalog ishlayveradi.
  }

  // Sayt birinchi ochilganda ism SO'RALMAYDI: avval mahsulotlar va sayt
  // ko'rsatiladi. Agar shu qurilma avval "Savatga" bosib, ismini kiritgan
  // bo'lsa, sayt uni o'zi taniydi va savatini tiklaydi.
  try {
    const customer = await api(`/customer/${state.deviceId}`);
    applyCustomer(customer);
    refreshCart();
  } catch (_) {
    // Hali ism kiritilmagan — hech narsa qilinmaydi, gate faqat
    // "Savatga" tugmasi bosilganda ochiladi.
  }

  try {
    state.categories = await api("/categories");
    renderFilters();
    el("statCategories").textContent = state.categories.length;
  } catch (_) {
    renderFilters();
  }

  await loadProducts();
}

init();
