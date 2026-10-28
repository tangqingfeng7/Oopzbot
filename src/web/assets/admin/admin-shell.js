(function () {
  const NAV_ITEMS = [
    { key: "dashboard", href: "/admin", label: "总览" },
    { key: "music", href: "/admin/music", label: "音乐" },
    { key: "config", href: "/admin/config", label: "配置" },
    { key: "screen-share", href: "/admin/screen-share", label: "屏幕共享" },
    { key: "stats", href: "/admin/stats", label: "统计" },
    { key: "activity", href: "/admin/activity", label: "活跃" },
    { key: "scheduler", href: "/admin/scheduler", label: "定时" },
    { key: "members", href: "/admin/members", label: "成员" },
    { key: "areas", href: "/admin/areas", label: "域管理" },
    { key: "plugins", href: "/admin/plugins", label: "插件" },
    { key: "setup", href: "/admin/setup", label: "体检" },
    { key: "system", href: "/admin/system", label: "系统" },
  ];

  function byId(target) {
    if (!target) {
      return null;
    }
    return typeof target === "string" ? document.getElementById(target) : target;
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  async function req(url, options) {
    const response = await fetch(url, {
      credentials: "include",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...((options && options.headers) || {}),
      },
      ...(options || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      const detail = Array.isArray(data.errors) && data.errors.length > 0
        ? data.errors.join(" | ")
        : "";
      throw new Error(data.error || detail || ("HTTP " + response.status));
    }
    return data;
  }

  function showMessage(target, text, isError) {
    const element = byId(target);
    if (!element) {
      return;
    }
    element.textContent = text || "";
    element.classList.toggle("is-error", !!isError);
    element.classList.toggle("is-success", !!text && !isError);
  }

  function setStatus(text, variant, target) {
    const element = byId(target || "topStatus");
    if (!element) {
      return;
    }
    const kind = variant === "error" ? "danger" : (variant || "neutral");
    element.textContent = text || "";
    element.className = "status-text";
    element.classList.add("is-" + kind);
  }

  function setMicroStatus(text, variant, target) {
    const element = byId(target);
    if (!element) {
      return;
    }
    const kind = variant === "error" ? "danger" : (variant || "neutral");
    element.textContent = text || "";
    element.className = "micro-status";
    element.classList.add("is-" + kind);
  }

  function formatNumber(value, finalValue) {
    const current = Number(value);
    const finalNumber = Number(finalValue ?? value);
    const integerMode = Number.isInteger(finalNumber);
    return new Intl.NumberFormat("zh-CN", {
      maximumFractionDigits: integerMode ? 0 : 2,
    }).format(current);
  }

  function animateNumber(target, nextValue) {
    const element = byId(target);
    if (!element) {
      return;
    }
    const parsed = Number(nextValue);
    if (!Number.isFinite(parsed)) {
      element.textContent = nextValue ?? "-";
      delete element.dataset.value;
      return;
    }
    const current = Number(element.dataset.value);
    element.dataset.value = String(parsed);
    if (!window.gsap || prefersReducedMotion() || !Number.isFinite(current)) {
      element.textContent = formatNumber(parsed);
      return;
    }
    const state = { value: current };
    window.gsap.to(state, {
      value: parsed,
      duration: 0.55,
      ease: "power2.out",
      onUpdate() {
        element.textContent = formatNumber(state.value, parsed);
      },
      onComplete() {
        element.textContent = formatNumber(parsed);
      },
    });
  }

  function flashUpdate(target) {
    const element = byId(target);
    if (!element || !window.gsap || prefersReducedMotion()) {
      return;
    }
    window.gsap.fromTo(
      element,
      { opacity: 0.55 },
      { opacity: 1, duration: 0.3, ease: "power2.out" }
    );
  }

  function getNavMarkup(currentPage) {
    return (
      '<div class="top-nav__marker"></div>' +
      NAV_ITEMS.map((item) => {
        const activeClass = item.key === currentPage ? " is-active" : "";
        const current = item.key === currentPage ? ' aria-current="page"' : "";
        return `<a class="nav-link${activeClass}" href="${item.href}" data-nav-key="${item.key}"${current}>${item.label}</a>`;
      }).join("")
    );
  }

  function updateNavMarker(container) {
    if (!container) {
      return;
    }
    const marker = container.querySelector(".top-nav__marker");
    const active = container.querySelector(".nav-link.is-active");
    if (!marker || !active) {
      return;
    }
    const left = active.offsetLeft;
    const width = active.offsetWidth;
    if (!window.gsap || prefersReducedMotion()) {
      marker.style.opacity = "1";
      marker.style.transform = "translateX(" + left + "px)";
      marker.style.width = width + "px";
      return;
    }
    window.gsap.to(marker, {
      x: left,
      width,
      opacity: 1,
      duration: 0.32,
      ease: "power2.out",
    });
  }

  function renderNav(currentPage) {
    const desktop = byId("topNav");
    const mobile = byId("mobileNav");
    const markup = getNavMarkup(currentPage);
    if (desktop) {
      desktop.innerHTML = markup;
    }
    if (mobile) {
      mobile.innerHTML = markup;
    }
    requestAnimationFrame(() => {
      updateNavMarker(desktop);
      updateNavMarker(mobile);
    });
  }

  function animateEnter() {
    if (!window.gsap || prefersReducedMotion()) {
      return;
    }
    var topbar = document.querySelector(".shell-topbar");
    var mobileNav = document.querySelector(".mobile-nav-shell");
    var hero = document.querySelector(".page-hero");
    var cards = document.querySelectorAll(
      ".auth-card, .surface-card, .metric-card, .summary-card, .table-card, .console-card, .sticky-rail"
    );
    var timeline = window.gsap.timeline({ defaults: { ease: "power3.out" } });

    if (topbar) {
      timeline.from(topbar, {
        y: -16,
        opacity: 0,
        scale: 0.98,
        duration: 0.45,
        clearProps: "transform,opacity",
      });
    }
    if (mobileNav) {
      timeline.from(
        mobileNav,
        {
          y: -10,
          opacity: 0,
          duration: 0.3,
          clearProps: "transform,opacity",
        },
        "-=0.25"
      );
    }
    if (hero) {
      timeline.from(
        hero,
        {
          y: 16,
          opacity: 0,
          scale: 0.98,
          duration: 0.35,
          clearProps: "transform,opacity",
        },
        "-=0.15"
      );
    }
    if (cards.length) {
      timeline.from(
        cards,
        {
          y: 20,
          opacity: 0,
          scale: 0.97,
          duration: 0.35,
          stagger: 0.05,
          clearProps: "transform,opacity",
        },
        "-=0.1"
      );
    }
  }

  function animatePanel(target) {
    const root = byId(target);
    if (!root || !window.gsap || prefersReducedMotion()) {
      return;
    }
    const cards = root.querySelectorAll(
      ".surface-card, .metric-card, .summary-card, .table-card, .console-card, .sticky-rail"
    );
    if (!cards.length) {
      return;
    }
    window.gsap.fromTo(
      cards,
      { y: 18, opacity: 0, scale: 0.97 },
      {
        y: 0,
        opacity: 1,
        scale: 1,
        duration: 0.35,
        stagger: 0.04,
        ease: "power2.out",
        clearProps: "transform,opacity",
      }
    );
  }

  function setAuthState(options) {
    const settings = {
      loginId: "loginCard",
      panelId: "panel",
      loggedInText: "已登录",
      loggedOutText: "等待登录",
      statusTargets: ["topStatus", "mobileStatus"],
      ...(options || {}),
    };
    const loginCard = byId(settings.loginId);
    const panel = byId(settings.panelId);

    if (loginCard) {
      loginCard.classList.toggle("hidden", !!settings.loggedIn);
    }
    if (panel) {
      panel.classList.toggle("hidden", !settings.loggedIn);
    }

    const text = settings.loggedIn ? settings.loggedInText : settings.loggedOutText;
    const variant = settings.loggedIn ? "success" : "warning";
    (settings.statusTargets || []).forEach((target) => {
      setStatus(text, variant, target);
    });

    if (settings.loggedIn && panel) {
      animatePanel(panel);
    }
  }

  function bindEnterSubmit(inputId, handler) {
    const input = byId(inputId);
    if (!input || input.dataset.enterBound === "1") {
      return;
    }
    input.dataset.enterBound = "1";
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") {
        return;
      }
      event.preventDefault();
      handler();
    });
  }

  async function copyText(value) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "absolute";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }

  function init(options) {
    const settings = options || {};
    const currentPage = settings.page || document.body.dataset.adminPage || "";
    renderNav(currentPage);
    animateEnter();
    if (settings.passwordHandler) {
      bindEnterSubmit(settings.passwordId || "pwd", settings.passwordHandler);
    }
    const refreshMarker = () => {
      updateNavMarker(byId("topNav"));
      updateNavMarker(byId("mobileNav"));
    };
    window.addEventListener("resize", refreshMarker);
    window.addEventListener("load", refreshMarker);
  }

  // -------------------------------------------------------------------------
  // 鉴权三件套（check/login/logout）的统一实现。
  // 各页只需提供 loggedInText 与登录成功后的 onLogin 加载回调，以及可选的
  // onLoggedOut（登出态额外状态）/ onLoginError（登录失败额外状态）；本函数
  // 负责绑定 window.login/window.logout（供 data-action 委托）、init 与首检。
  // -------------------------------------------------------------------------
  function bootstrapAuth(options) {
    const settings = options || {};
    const loggedInText = settings.loggedInText || "已登录";
    const loggedOutText = settings.loggedOutText || "等待登录";
    const statusTargets = settings.statusTargets || ["topStatus", "mobileStatus"];
    const passwordId = settings.passwordId || "pwd";
    const loginMsgId = settings.loginMsgId || "loginMsg";
    const meUrl = settings.meUrl || "/admin/api/me";
    const loginUrl = settings.loginUrl || "/admin/api/login";
    const logoutUrl = settings.logoutUrl || "/admin/api/logout";
    const successMessage =
      settings.loginSuccessMessage === undefined ? "登录成功" : settings.loginSuccessMessage;

    async function check() {
      try {
        await req(meUrl);
        setAuthState({ loggedIn: true, loggedInText, statusTargets });
        if (settings.onLogin) {
          await settings.onLogin();
        }
      } catch (error) {
        setAuthState({ loggedIn: false, loggedOutText, statusTargets });
        showMessage(loginMsgId, "");
        if (settings.onLoggedOut) {
          settings.onLoggedOut(error);
        }
      }
    }

    async function login() {
      try {
        const input = byId(passwordId);
        await req(loginUrl, {
          method: "POST",
          body: JSON.stringify({ password: (input && input.value) || "" }),
        });
        if (successMessage) {
          showMessage(loginMsgId, successMessage);
        }
        await check();
      } catch (error) {
        showMessage(loginMsgId, error.message, true);
        if (settings.onLoginError) {
          settings.onLoginError(error);
        }
      }
    }

    async function logout() {
      try {
        await req(logoutUrl, { method: "POST", body: "{}" });
      } catch (_) {}
      await check();
    }

    window.login = login;
    window.logout = logout;
    init({ page: settings.page, passwordId, passwordHandler: login });
    check();
    return { check, login, logout };
  }

  // -------------------------------------------------------------------------
  // Custom Select (replaces native <select> with styled dropdown)
  // -------------------------------------------------------------------------

  var _csInstances = new Map();

  function _csSetElevated(wrap, elevated) {
    var targets = [
      wrap.closest(".field"),
      wrap.closest(".surface-card, .table-card, .action-row"),
    ];
    targets.forEach(function (target) {
      if (target) target.classList.toggle("cs-elevated", elevated);
    });
  }

  function _csClose(wrap) {
    wrap.classList.remove("is-open");
    _csSetElevated(wrap, false);
  }

  function _csCloseAll(except) {
    _csInstances.forEach(function (inst) {
      if (inst.wrap !== except) _csClose(inst.wrap);
    });
  }

  document.addEventListener("click", function (e) {
    _csInstances.forEach(function (inst) {
      if (!inst.wrap.contains(e.target)) _csClose(inst.wrap);
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") _csCloseAll();
  });

  function upgradeSelect(selectId) {
    var sel = byId(selectId);
    if (!sel || sel.tagName !== "SELECT") return null;

    var existing = _csInstances.get(selectId);
    if (existing) return existing;

    var wrap = document.createElement("div");
    wrap.className = "cs-wrap";
    if (sel.classList.contains("m-area-select")) {
      wrap.style.maxWidth = "200px";
    }

    var trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "cs-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");

    var dropdown = document.createElement("div");
    dropdown.className = "cs-dropdown";
    dropdown.setAttribute("role", "listbox");

    sel.style.display = "none";
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(trigger);
    wrap.appendChild(dropdown);
    wrap.appendChild(sel);

    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      var isOpen = wrap.classList.contains("is-open");
      _csCloseAll();
      if (!isOpen) {
        wrap.classList.add("is-open");
        _csSetElevated(wrap, true);
        var selected = dropdown.querySelector(".is-selected");
        if (selected) selected.scrollIntoView({ block: "nearest" });
      }
    });

    function syncOptions() {
      dropdown.innerHTML = "";
      var opts = sel.options;
      if (!opts.length) {
        dropdown.innerHTML = '<span class="cs-empty">无选项</span>';
        trigger.textContent = "请选择";
        return;
      }
      var children = sel.children;
      for (var c = 0; c < children.length; c++) {
        var child = children[c];
        if (child.tagName === "OPTGROUP") {
          var groupLabel = document.createElement("div");
          groupLabel.className = "cs-group-label";
          groupLabel.textContent = child.label || "";
          dropdown.appendChild(groupLabel);
          for (var g = 0; g < child.children.length; g++) {
            _appendOption(child.children[g]);
          }
        } else if (child.tagName === "OPTION") {
          _appendOption(child);
        }
      }
      _refreshSelected();
    }

    function _appendOption(opt) {
      var idx = opt.index;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cs-option";
      btn.setAttribute("role", "option");
      btn.textContent = opt.text;
      btn.dataset.value = opt.value;
      btn.dataset.idx = idx;
      if (idx === sel.selectedIndex) btn.classList.add("is-selected");
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        sel.selectedIndex = idx;
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        _refreshSelected();
        _csClose(wrap);
      });
      dropdown.appendChild(btn);
    }

    function _refreshSelected() {
      var idx = sel.selectedIndex;
      trigger.textContent = idx >= 0 && sel.options[idx] ? sel.options[idx].text : "请选择";
      var btns = dropdown.querySelectorAll(".cs-option");
      btns.forEach(function (b) {
        b.classList.toggle("is-selected", parseInt(b.dataset.idx, 10) === idx);
      });
    }

    var observer = new MutationObserver(function () {
      syncOptions();
    });
    observer.observe(sel, { childList: true, subtree: true, attributes: true });

    syncOptions();

    var inst = { wrap: wrap, trigger: trigger, dropdown: dropdown, sel: sel, sync: syncOptions };
    _csInstances.set(selectId, inst);
    return inst;
  }

  function refreshCustomSelect(selectId) {
    var inst = _csInstances.get(selectId);
    if (inst) inst.sync();
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  // -------------------------------------------------------------------------
  // Modal subsystem (shared dialog reused across admin pages)
  // Pages must provide #modalOverlay / #modalDialog / #modalTitle /
  // #modalBody / #modalFooter in their markup.
  // -------------------------------------------------------------------------

  let _modalCloseCb = null;

  function _modalEls() {
    return {
      overlay: byId("modalOverlay"),
      dialog: byId("modalDialog"),
      title: byId("modalTitle"),
      body: byId("modalBody"),
      footer: byId("modalFooter"),
    };
  }

  function openModal(title, bodyHtml, footerHtml, onClose) {
    const els = _modalEls();
    if (!els.dialog || !els.overlay) {
      return els;
    }
    _modalCloseCb = typeof onClose === "function" ? onClose : null;
    if (els.title) {
      els.title.textContent = title || "";
    }
    if (els.body) {
      els.body.innerHTML = bodyHtml || "";
    }
    if (els.footer) {
      els.footer.innerHTML = footerHtml || "";
    }
    els.overlay.classList.add("is-open");
    els.dialog.classList.add("is-open");
    return els;
  }

  function closeModal() {
    const els = _modalEls();
    if (els.dialog) {
      els.dialog.classList.remove("is-open");
    }
    if (els.overlay) {
      els.overlay.classList.remove("is-open");
    }
    const cb = _modalCloseCb;
    _modalCloseCb = null;
    if (cb) {
      cb();
    }
  }

  // 跨域视图下同一个人可能属于多个域，管理操作必须先问清楚打到哪个域。
  // 返回选中的 areaId，取消则返回空串。
  function pickArea(areas) {
    return new Promise((resolve) => {
      const els = _modalEls();
      if (!els.dialog || !els.footer) {
        resolve("");
        return;
      }
      let settled = false;
      const done = (value) => {
        if (settled) {
          return;
        }
        settled = true;
        closeModal();
        resolve(value);
      };
      const body = document.createElement("div");
      body.className = "m-area-pick";
      areas.forEach((a) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-ghost m-area-pick__item";
        btn.textContent = a.areaName || a.areaId;
        btn.addEventListener("click", () => done(a.areaId));
        body.appendChild(btn);
      });
      openModal(
        "选择域",
        '<div class="m-confirm-text">该成员同时在多个域，请选择本次操作生效的域：</div>',
        null,
        () => {
          if (!settled) {
            settled = true;
            resolve("");
          }
        }
      );
      if (els.body) {
        els.body.appendChild(body);
      }
      els.footer.innerHTML = "";
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "btn btn-ghost";
      cancelBtn.textContent = "取消";
      cancelBtn.addEventListener("click", () => done(""));
      els.footer.appendChild(cancelBtn);
    });
  }

  function confirm(title, message, options) {
    const opts = options || {};
    return new Promise((resolve) => {
      const els = _modalEls();
      if (!els.dialog || !els.footer) {
        resolve(false);
        return;
      }
      let settled = false;
      const done = (value) => {
        if (settled) {
          return;
        }
        settled = true;
        closeModal();
        resolve(value);
      };
      openModal(
        title,
        '<div class="m-confirm-text">' + (message || "") + "</div>",
        null,
        () => {
          if (!settled) {
            settled = true;
            resolve(false);
          }
        }
      );
      els.footer.innerHTML = "";
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "btn btn-ghost";
      cancelBtn.textContent = opts.cancelText || "取消";
      cancelBtn.addEventListener("click", () => done(false));
      const okBtn = document.createElement("button");
      okBtn.className = "btn " + (opts.danger === false ? "btn-primary" : "btn-danger");
      okBtn.textContent = opts.okText || "确认";
      okBtn.addEventListener("click", () => done(true));
      els.footer.appendChild(cancelBtn);
      els.footer.appendChild(okBtn);
    });
  }

  // -------------------------------------------------------------------------
  // Action registry (data-action + event delegation)
  // Pages register handlers by action key; topbar/page buttons carry only
  // data-action so behavior stays in JS instead of inline onclick markup.
  // -------------------------------------------------------------------------

  const _actionHandlers = Object.create(null);
  // 内置动作：所有页面共用的弹窗关闭与登录/登出，免去逐页重复注册。
  // login/logout 由各页脚本定义为全局函数，点击时已就绪。
  _actionHandlers["close-modal"] = () => closeModal();
  _actionHandlers["login"] = () => {
    if (typeof window.login === "function") {
      window.login();
    }
  };
  _actionHandlers["logout"] = () => {
    if (typeof window.logout === "function") {
      window.logout();
    }
  };

  function registerActions(handlers) {
    Object.assign(_actionHandlers, handlers || {});
  }

  function _dispatch(trigger, key, event) {
    const handler = _actionHandlers[key];
    if (!handler) {
      return;
    }
    Promise.resolve()
      .then(() => handler(trigger, event))
      .catch(() => {});
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-action]");
    if (!trigger) {
      return;
    }
    event.preventDefault();
    _dispatch(trigger, trigger.dataset.action, event);
  });

  // 委托 change 事件：select / checkbox 用 data-change 指定动作键，
  // 处理函数从入参 el 读取 .value / .checked。
  document.addEventListener("change", (event) => {
    const trigger = event.target.closest("[data-change]");
    if (!trigger) {
      return;
    }
    _dispatch(trigger, trigger.dataset.change, event);
  });

  // 委托 Enter 键：输入框用 data-enter 指定动作键，仅在按下回车时触发。
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") {
      return;
    }
    const trigger = event.target.closest("[data-enter]");
    if (!trigger) {
      return;
    }
    event.preventDefault();
    _dispatch(trigger, trigger.dataset.enter, event);
  });

  // ---- 域切换标签页 ----
  // 域一般只有几个，平铺出来一眼可见、点一下就切，比下拉少两次交互。
  // 滚轮横向滚动（浏览器默认要按住 Shift）；按住标签左右拖动可调整顺序，
  // 顺序存在浏览器本地，排在最前的域即为下次打开时默认加载的域。
  // 隐藏的 <select> 仍然保留并保持同步——页面脚本继续用 byId(id).value 读取，
  // data-change 的回调也照旧触发，改造不需要动各页面的既有逻辑。

  var AREA_ORDER_KEY = "adminAreaOrder";

  function _loadAreaOrder() {
    try {
      var raw = window.localStorage.getItem(AREA_ORDER_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function _saveAreaOrder(ids) {
    try {
      window.localStorage.setItem(AREA_ORDER_KEY, JSON.stringify(ids));
    } catch (e) {
      /* 隐私模式等场景写不了，顺序退化为接口返回的原始顺序 */
    }
  }

  // 按保存的顺序重排真实域；"全部域" 恒定钉在最前，不参与排序也不作为默认。
  function applyAreaOrder(areas) {
    var saved = _loadAreaOrder();
    if (!saved.length) return areas;
    var byId2 = {};
    areas.forEach(function (a) { byId2[a.id] = a; });
    var ordered = [];
    saved.forEach(function (id) {
      if (byId2[id]) { ordered.push(byId2[id]); delete byId2[id]; }
    });
    // 保存顺序里没有的（新加入的域）追加在后面，不丢
    areas.forEach(function (a) { if (byId2[a.id]) ordered.push(a); });
    return ordered;
  }

  function _bindTabsWheel(box) {
    if (box.dataset.wheelBound === "1") return;
    box.dataset.wheelBound = "1";
    box.addEventListener("wheel", function (e) {
      if (box.scrollWidth <= box.clientWidth) return;
      var delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (!delta) return;
      e.preventDefault();
      box.scrollLeft += delta;
    }, { passive: false });
  }

  function renderAreaTabs(selectId, containerId, onReorder) {
    var sel = byId(selectId);
    var box = byId(containerId);
    if (!sel || !box) return;

    _bindTabsWheel(box);
    box.innerHTML = "";
    var options = Array.prototype.slice.call(sel.options).filter(function (opt) {
      return opt.value;
    });
    if (!options.length) {
      box.innerHTML = '<span class="area-tabs-empty">无可用域</span>';
      return;
    }

    function persistOrder() {
      var ids = Array.prototype.slice.call(box.querySelectorAll(".area-tab"))
        .map(function (el) { return el.dataset.value; })
        .filter(function (v) { return v && v !== "__all__"; });
      _saveAreaOrder(ids);
      // 把新顺序同步回隐藏 select，保证「第一个」的语义处处一致
      var frag = document.createDocumentFragment();
      var all = sel.querySelector('option[value="__all__"]');
      if (all) frag.appendChild(all);
      ids.forEach(function (id) {
        var opt = sel.querySelector('option[value="' + CSS.escape(id) + '"]');
        if (opt) frag.appendChild(opt);
      });
      sel.appendChild(frag);
      if (typeof onReorder === "function") onReorder(ids);
    }

    options.forEach(function (opt) {
      var isAll = opt.value === "__all__";
      var tab = document.createElement("button");
      tab.type = "button";
      tab.className = "area-tab" + (opt.value === sel.value ? " is-active" : "")
        + (isAll ? " area-tab--all" : "");
      tab.textContent = opt.textContent || opt.value;
      tab.title = isAll ? opt.textContent : (opt.textContent || opt.value) + "（可拖动调整顺序）";
      tab.dataset.value = opt.value;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", opt.value === sel.value ? "true" : "false");
      if (!isAll) tab.draggable = true;

      tab.addEventListener("click", function () {
        if (box._suppressClickUntil && Date.now() < box._suppressClickUntil) return;
        if (sel.value === opt.value) return;
        sel.value = opt.value;
        renderAreaTabs(selectId, containerId, onReorder);
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      });

      if (!isAll) {
        tab.addEventListener("dragstart", function (e) {
          box._dragging = tab;
          tab.classList.add("is-ghost");
          try { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", opt.value); } catch (err) { /* 忽略 */ }
        });
        tab.addEventListener("dragend", function () {
          tab.classList.remove("is-ghost");
          box._dragging = null;
          // 拖完立刻的 click 不该被当成切域
          box._suppressClickUntil = Date.now() + 250;
          persistOrder();
        });
        tab.addEventListener("dragover", function (e) {
          e.preventDefault();
          var dragged = box._dragging;
          if (!dragged || dragged === tab) return;
          var rect = tab.getBoundingClientRect();
          var after = e.clientX > rect.left + rect.width / 2;
          box.insertBefore(dragged, after ? tab.nextSibling : tab);
        });
      }
      box.appendChild(tab);
    });

    box.addEventListener("dragover", function (e) { e.preventDefault(); });

    var active = box.querySelector(".area-tab.is-active");
    if (active && box.scrollWidth > box.clientWidth) {
      active.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  window.AdminShell = {
    animateNumber,
    animatePanel,
    bootstrapAuth,
    byId,
    applyAreaOrder,
    renderAreaTabs,
    closeModal,
    confirm,
    pickArea,
    copyText,
    escapeHtml,
    flashUpdate,
    init,
    openModal,
    refreshCustomSelect,
    registerActions,
    req,
    setAuthState,
    setMicroStatus,
    setStatus,
    showMessage,
    updateNavMarker,
    upgradeSelect,
  };
})();
