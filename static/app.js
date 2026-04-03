// gallery-dl-viewer — client-side JS
// Handles: infinite scroll, filter form, favorites

(function () {
  "use strict";

  // -------------------------------------------------------------------------
  // Mobile video autoplay via IntersectionObserver
  // (mouseenter/mouseleave does not fire on touch devices)
  // -------------------------------------------------------------------------

  const IS_TOUCH = ('ontouchstart' in window) || navigator.maxTouchPoints > 0;

  const videoObserver = IS_TOUCH ? new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.play().catch(() => {});
      } else {
        entry.target.pause();
      }
    });
  }, { threshold: 0.4 }) : null;

  function observeVideos(root) {
    if (!videoObserver) return;
    root.querySelectorAll('video').forEach(v => videoObserver.observe(v));
  }

  // -------------------------------------------------------------------------
  // Favorite helpers
  // -------------------------------------------------------------------------

  const HEART_FILLED = `<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>`;
  const HEART_OUTLINE = `<svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"/></svg>`;

  function setHeartState(btn, favorited) {
    btn.innerHTML = favorited ? HEART_FILLED : HEART_OUTLINE;
    if (favorited) {
      btn.classList.add("text-red-500");
      btn.classList.remove("text-white", "opacity-0", "group-hover:opacity-70");
    } else {
      btn.classList.remove("text-red-500");
      btn.classList.add("text-white", "opacity-0", "group-hover:opacity-70");
    }
  }

  async function toggleFavMedia(mediaId) {
    try {
      const res = await fetch(`/api/favorite/media/${mediaId}`, { method: "POST" });
      if (!res.ok) return;
      const { favorited } = await res.json();
      if (favorited) {
        FAV_MEDIA_IDS.add(mediaId);
      } else {
        FAV_MEDIA_IDS.delete(mediaId);
      }
      document.querySelectorAll(`.fav-btn[data-media-id="${mediaId}"]`).forEach((btn) => {
        setHeartState(btn, favorited);
      });
    } catch (e) {
      console.error("Failed to toggle media favorite:", e);
    }
  }

  async function toggleFavTag(tag, btn) {
    try {
      const res = await fetch(`/api/favorite/tag/${encodeURIComponent(tag)}`, { method: "POST" });
      if (!res.ok) return;
      const { favorited } = await res.json();
      btn.dataset.fav = favorited ? "true" : "false";
      btn.textContent = favorited ? "★" : "☆";
      if (favorited) {
        btn.classList.add("text-yellow-400");
        btn.classList.remove("text-gray-600");
      } else {
        btn.classList.remove("text-yellow-400");
        btn.classList.add("text-gray-600");
      }
    } catch (e) {
      console.error("Failed to toggle tag favorite:", e);
    }
  }

  // -------------------------------------------------------------------------
  // Infinite scroll
  // -------------------------------------------------------------------------

  const grid = document.getElementById("grid");
  const sentinel = document.getElementById("sentinel");
  const loadingEl = document.getElementById("loading");
  const noMoreEl = document.getElementById("no-more");

  if (!grid || !sentinel) return; // not on gallery page

  let offset = typeof INITIAL_COUNT !== "undefined" ? INITIAL_COUNT : 24;
  let loading = false;
  let done = offset === 0;

  function buildApiUrl(off) {
    const p = new URLSearchParams();
    if (FILTERS.tags)      p.set("tags",      FILTERS.tags);
    if (FILTERS.q)         p.set("q",         FILTERS.q);
    if (FILTERS.from_date) p.set("from_date", FILTERS.from_date);
    if (FILTERS.to_date)   p.set("to_date",   FILTERS.to_date);
    if (FILTERS.order)     p.set("order",     FILTERS.order);
    if (FILTERS.fav_only)  p.set("fav_only",  "1");
    p.set("offset", off);
    p.set("limit",  24);
    return "/api/gallery?" + p.toString();
  }

  function createCard(item) {
    const a = document.createElement("a");
    a.href = `/post/${item.tweet_id}`;
    a.className = "block relative group bg-gray-900 rounded overflow-hidden";

    const isVideo = item.media_type === "video";
    const mediaHtml = isVideo
      ? `<video src="/media/${item.id}"
           class="w-full h-full object-cover"
           muted loop playsinline preload="metadata"
           onmouseenter="this.play()" onmouseleave="this.pause()"></video>`
      : `<img src="/media/${item.id}"
           class="w-full h-full object-cover"
           loading="lazy" alt=""
           onerror="onImgError(this)">`;

    const isFav = FAV_MEDIA_IDS.has(item.id);
    const heartCls = isFav
      ? "text-red-500"
      : "text-white opacity-0 group-hover:opacity-70";
    const heartSvg = isFav ? HEART_FILLED : HEART_OUTLINE;

    const badgeHtml = isVideo
      ? `<div class="absolute top-1.5 right-1.5 bg-black/70 rounded px-1 py-0.5 text-xs text-gray-300">▸</div>`
      : "";

    const date = item.date ? item.date.slice(0, 10) : "";
    const nick = item.author_nick || item.author_name || "";
    if (date) a.dataset.date = date;

    a.innerHTML = `
      <div class="aspect-square bg-gray-800">${mediaHtml}</div>
      <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent
                  opacity-0 group-hover:opacity-100 transition-opacity duration-150
                  flex flex-col justify-end p-2 pointer-events-none">
        <div class="text-xs text-white font-medium truncate">${escHtml(nick)}</div>
        <div class="text-xs text-gray-300">${escHtml(date)}</div>
      </div>
      <button type="button"
              class="fav-btn absolute top-1.5 left-1.5 drop-shadow transition-opacity duration-150 ${heartCls}"
              data-media-id="${item.id}">
        ${heartSvg}
      </button>
      ${badgeHtml}
    `;
    return a;
  }

  function escHtml(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  async function loadMore() {
    if (loading || done) return;
    loading = true;
    loadingEl.classList.remove("hidden");

    try {
      const res = await fetch(buildApiUrl(offset));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const items = await res.json();

      items.forEach((item) => {
        const card = createCard(item);
        grid.appendChild(card);
        observeVideos(card);
      });
      offset += items.length;

      if (items.length < 24) {
        done = true;
        noMoreEl.classList.remove("hidden");
        observer.disconnect();
      }
    } catch (e) {
      console.error("Failed to load more:", e);
    } finally {
      loading = false;
      loadingEl.classList.add("hidden");
    }
  }

  const observer = new IntersectionObserver(
    (entries) => { if (entries[0].isIntersecting) loadMore(); },
    { rootMargin: "300px" }
  );
  observer.observe(sentinel);

  // Observe SSR-rendered video cards for mobile autoplay
  observeVideos(grid);

  // -------------------------------------------------------------------------
  // Heart button — event delegation on grid
  // -------------------------------------------------------------------------

  grid.addEventListener("click", (e) => {
    const btn = e.target.closest(".fav-btn");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    toggleFavMedia(Number(btn.dataset.mediaId));
  });

  // -------------------------------------------------------------------------
  // Tag favorite buttons
  // -------------------------------------------------------------------------

  document.querySelectorAll(".fav-tag-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleFavTag(btn.dataset.tag, btn).then(() => {
        if (favTagsCheckbox?.checked) applyFavTagsFilter(true);
      });
    });
  });

  // fav-tags-only toggle: immediate client-side filter + checkbox sync
  const favTagsToggle = document.getElementById("fav-tags-toggle");
  const favTagsCheckbox = favTagsToggle?.previousElementSibling;

  function applyFavTagsFilter(active) {
    document.querySelectorAll(".fav-tag-item").forEach((item) => {
      const btn = item.querySelector(".fav-tag-btn");
      const isFav = btn?.dataset.fav === "true";
      item.style.display = (active && !isFav) ? "none" : "";
    });
  }

  if (favTagsToggle && favTagsCheckbox) {
    // Apply initial state (page may load with fav_tags_only=1 from URL)
    applyFavTagsFilter(favTagsCheckbox.checked);

    favTagsToggle.addEventListener("click", () => {
      favTagsCheckbox.checked = !favTagsCheckbox.checked;
      const active = favTagsCheckbox.checked;
      favTagsToggle.classList.toggle("border-yellow-400", active);
      favTagsToggle.classList.toggle("text-yellow-400", active);
      favTagsToggle.classList.toggle("border-gray-600", !active);
      favTagsToggle.classList.toggle("text-gray-500", !active);
      applyFavTagsFilter(active);
    });
  }


  // -------------------------------------------------------------------------
  // Filter navigation — shared logic used by Apply, Sort, fav_only, keyword Enter
  // -------------------------------------------------------------------------

  const form = document.getElementById("filter-form");

  function navigateWithFilters() {
    if (!form) return;
    const checked = [...form.querySelectorAll("input[name='tags_check']:checked")]
      .map((cb) => cb.value.trim())
      .filter(Boolean);

    const q             = form.querySelector("input[name='q']").value.trim();
    const from_date     = form.querySelector("input[name='from_date']").value;
    const to_date       = form.querySelector("input[name='to_date']").value;
    const order         = form.querySelector("input[name='order']:checked")?.value || "desc";
    const fav_only      = form.querySelector("input[name='fav_only']")?.checked;
    const fav_tags_only = form.querySelector("input[name='fav_tags_only']")?.checked;

    const params = new URLSearchParams();
    if (checked.length)   params.set("tags",         checked.join(","));
    if (q)                params.set("q",             q);
    if (from_date)        params.set("from_date",     from_date);
    if (to_date)          params.set("to_date",       to_date);
    if (order !== "desc") params.set("order",         order);
    if (fav_only)         params.set("fav_only",      "1");
    if (fav_tags_only)    params.set("fav_tags_only", "1");

    window.location.href = "/?" + params.toString();
  }

  if (form) {
    // Apply button
    form.addEventListener("submit", (e) => { e.preventDefault(); navigateWithFilters(); });

    // Keyword: navigate on Enter (default submit behaviour already handled above,
    // but keep explicit for clarity — no extra handler needed)

    // ♥ Posts only: navigate immediately on change
    form.querySelector("input[name='fav_only']")
      ?.addEventListener("change", navigateWithFilters);

    // Keyword: navigate on Enter key
    form.querySelector("input[name='q']")
      ?.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); navigateWithFilters(); } });
  }

  // -------------------------------------------------------------------------
  // Sort order toggle — update label styles + navigate immediately on change
  // -------------------------------------------------------------------------

  const orderLabels = document.querySelectorAll(".order-label");
  function updateOrderStyles() {
    orderLabels.forEach((label) => {
      const radio = label.querySelector("input[type='radio']");
      if (radio.checked) {
        label.classList.add("bg-blue-600", "text-white");
        label.classList.remove("bg-gray-800", "text-gray-400", "hover:bg-gray-700");
      } else {
        label.classList.remove("bg-blue-600", "text-white");
        label.classList.add("bg-gray-800", "text-gray-400", "hover:bg-gray-700");
      }
    });
  }
  orderLabels.forEach((label) => {
    label.addEventListener("change", () => { updateOrderStyles(); navigateWithFilters(); });
  });
  updateOrderStyles();
})();

// =============================================================================
// Timeline scrubber
// =============================================================================
(function () {
  "use strict";

  const scrubberEl = document.getElementById("tl-scrubber");
  const track      = document.getElementById("tl-track");
  const labelEl    = document.getElementById("tl-label");
  if (!scrubberEl || !track || !labelEl) return;

  const dateMin = typeof DATE_MIN !== "undefined" ? DATE_MIN : "";
  const dateMax = typeof DATE_MAX !== "undefined" ? DATE_MAX : "";
  if (!dateMin || !dateMax || dateMin === dateMax) return;

  const orderDesc = (typeof FILTERS === "undefined" || FILTERS.order !== "asc");
  const minMs = new Date(dateMin).getTime();
  const maxMs = new Date(dateMax).getTime();
  const spanMs = maxMs - minMs;

  // Date string → track fraction from top (0 = top, 1 = bottom)
  function dateToPct(dateStr) {
    const raw = (new Date(dateStr).getTime() - minMs) / spanMs;
    return orderDesc ? 1 - raw : raw;
  }

  // Track fraction from top → { label, dateStr, yearMonth }
  function pctToInfo(pct) {
    const raw = orderDesc ? 1 - pct : pct;
    const ms  = minMs + Math.max(0, Math.min(1, raw)) * spanMs;
    const d   = new Date(ms);
    const y   = d.getFullYear();
    const m   = d.getMonth() + 1;
    return {
      label:     `${y}年${m}月`,
      dateStr:   `${y}-${String(m).padStart(2, "0")}-01`,
      yearMonth: `${y}-${String(m).padStart(2, "0")}`,
    };
  }

  function formatLabel(dateStr) {
    if (!dateStr || dateStr.length < 7) return "";
    const y = parseInt(dateStr.slice(0, 4), 10);
    const m = parseInt(dateStr.slice(5, 7), 10);
    return `${y}年${m}月`;
  }

  // ---- Build year / month tick marks inside the track ----
  function buildTicks() {
    const spanMonths = spanMs / (30 * 24 * 3600 * 1000);
    const monthly    = spanMonths <= 24;
    const minYear    = new Date(dateMin).getFullYear();
    const maxYear    = new Date(dateMax).getFullYear();

    for (let y = minYear; y <= maxYear; y++) {
      if (monthly) {
        const mStart = (y === minYear) ? new Date(dateMin).getMonth() + 1 : 1;
        const mEnd   = (y === maxYear) ? new Date(dateMax).getMonth() + 1 : 12;
        for (let mo = mStart; mo <= mEnd; mo++) {
          const ds  = `${y}-${String(mo).padStart(2, "0")}-01`;
          const pct = dateToPct(ds);
          if (pct < 0 || pct > 1) continue;
          if (mo === 1 || mo === mStart) {
            addYearTick(y, pct);
          } else {
            addMinorTick(pct);
          }
        }
      } else {
        const pct = dateToPct(`${y}-01-01`);
        if (pct < 0 || pct > 1) continue;
        addYearTick(y, pct);
      }
    }
  }

  function addYearTick(year, pct) {
    const tick = document.createElement("div");
    tick.style.cssText = `position:absolute;left:0;right:0;height:1px;top:${pct * 100}%;background:rgba(107,114,128,0.5);pointer-events:none`;
    track.appendChild(tick);

    const lbl = document.createElement("div");
    lbl.style.cssText = `position:absolute;right:8px;top:${pct * 100}%;transform:translateY(-50%);` +
      `font-size:10px;color:rgba(156,163,175,0.8);pointer-events:none;white-space:nowrap`;
    lbl.textContent = year;
    track.appendChild(lbl);
  }

  function addMinorTick(pct) {
    const tick = document.createElement("div");
    tick.style.cssText = `position:absolute;left:25%;right:0;height:1px;top:${pct * 100}%;background:rgba(107,114,128,0.25);pointer-events:none`;
    track.appendChild(tick);
  }

  // ---- Label show / hide ----
  let hideTimer = null;

  function showLabel(pct, text) {
    labelEl.textContent = text;
    labelEl.style.top   = (pct * 100) + "%";
    labelEl.style.display = "";
  }

  function scheduleHide(ms) {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { labelEl.style.display = "none"; }, ms);
  }

  // ---- Scroll tracking ----
  let scrollRaf = null;

  function updateFromScroll() {
    const cards = document.querySelectorAll("#grid > a[data-date]");
    if (!cards.length) return;
    for (const card of cards) {
      if (card.getBoundingClientRect().bottom > 58) {
        const d = card.dataset.date;
        if (d) { showLabel(dateToPct(d), formatLabel(d)); scheduleHide(1500); }
        return;
      }
    }
  }

  window.addEventListener("scroll", () => {
    if (scrollRaf) return;
    scrollRaf = requestAnimationFrame(() => { scrollRaf = null; updateFromScroll(); });
  }, { passive: true });

  // ---- Track interaction ----
  function getTrackPct(clientY) {
    const r = track.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientY - r.top) / r.height));
  }

  let dragging = false;

  track.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  track.addEventListener("mouseleave", () => { if (!dragging) scheduleHide(400); });
  track.addEventListener("mousemove",  (e) => {
    if (dragging) return;
    const pct = getTrackPct(e.clientY);
    showLabel(pct, pctToInfo(pct).label);
  });
  track.addEventListener("mousedown", (e) => {
    dragging = true;
    e.preventDefault();
    const pct = getTrackPct(e.clientY);
    showLabel(pct, pctToInfo(pct).label);
  });

  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const pct = getTrackPct(e.clientY);
    showLabel(pct, pctToInfo(pct).label);
  });
  document.addEventListener("mouseup", (e) => {
    if (!dragging) return;
    dragging = false;
    navigateToDate(pctToInfo(getTrackPct(e.clientY)));
    scheduleHide(1500);
  });

  // Touch support
  track.addEventListener("touchstart", (e) => {
    dragging = true;
    e.preventDefault();
    const pct = getTrackPct(e.touches[0].clientY);
    showLabel(pct, pctToInfo(pct).label);
  }, { passive: false });
  document.addEventListener("touchmove", (e) => {
    if (!dragging) return;
    const pct = getTrackPct(e.touches[0].clientY);
    showLabel(pct, pctToInfo(pct).label);
  }, { passive: true });
  document.addEventListener("touchend", (e) => {
    if (!dragging) return;
    dragging = false;
    navigateToDate(pctToInfo(getTrackPct(e.changedTouches[0].clientY)));
  });

  // ---- Navigate to a date ----
  function navigateToDate(info) {
    // 1. Scroll to already-loaded card if possible
    const cards = [...document.querySelectorAll("#grid > a[data-date]")];
    if (cards.length) {
      let target = null;
      if (orderDesc) {
        target = cards.find(c => c.dataset.date && c.dataset.date.slice(0, 7) <= info.yearMonth);
      } else {
        target = cards.find(c => c.dataset.date && c.dataset.date.slice(0, 7) >= info.yearMonth);
      }
      if (target) { target.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    }

    // 2. Full navigation with date filter
    const p = new URLSearchParams();
    const F = typeof FILTERS !== "undefined" ? FILTERS : {};
    if (F.tags)          p.set("tags",          F.tags);
    if (F.q)             p.set("q",             F.q);
    if (F.fav_only)      p.set("fav_only",      "1");
    if (F.fav_tags_only) p.set("fav_tags_only", "1");
    if (F.order && F.order !== "desc") p.set("order", F.order);

    if (orderDesc) {
      if (F.from_date) p.set("from_date", F.from_date);
      p.set("to_date", info.dateStr);
    } else {
      if (F.to_date) p.set("to_date", F.to_date);
      p.set("from_date", info.dateStr);
    }
    window.location.href = "/?" + p.toString();
  }

  // ---- Init ----
  scrubberEl.style.display = "";
  buildTicks();
  updateFromScroll();
})();
