(function () {
  const NAV_ITEMS = [
    { key: "dashboard", href: "/admin", label: "总览" },
    { key: "music", href: "/admin/music", label: "音乐" },
    { key: "config", href: "/admin/config", label: "配置" },
    { key: "stats", href: "/admin/stats", label: "统计" },
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
      throw new Error(data.error || ("HTTP " + response.status));
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
    const topbar = document.querySelector(".shell-topbar");
    const mobileNav = document.querySelector(".mobile-nav-shell");
    const hero = document.querySelector(".page-hero");
    const cards = document.querySelectorAll(
      ".auth-card, .surface-card, .metric-card, .summary-card, .table-card, .console-card, .sticky-rail"
    );
    const timeline = window.gsap.timeline({ defaults: { ease: "power3.out" } });

    if (topbar) {
      timeline.from(topbar, {
        y: -8,
        opacity: 0,
        duration: 0.28,
      });
    }
    if (mobileNav) {
      timeline.from(
        mobileNav,
        {
          y: -6,
          opacity: 0,
          duration: 0.2,
        },
        "-=0.12"
      );
    }
    if (hero) {
      timeline.from(
        hero,
        {
          y: 8,
          opacity: 0,
          duration: 0.22,
        },
        "-=0.08"
      );
    }
    if (cards.length) {
      timeline.from(
        cards,
        {
          y: 8,
          opacity: 0,
          duration: 0.2,
          stagger: 0.03,
        },
        "-=0.04"
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
      { y: 8, opacity: 0 },
      {
        y: 0,
        opacity: 1,
        duration: 0.22,
        stagger: 0.02,
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

  function bindHoverMotion() {
    return;
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
    bindHoverMotion();
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

  window.AdminShell = {
    animateNumber,
    animatePanel,
    byId,
    copyText,
    flashUpdate,
    init,
    req,
    setAuthState,
    setMicroStatus,
    setStatus,
    showMessage,
    updateNavMarker,
  };
})();
