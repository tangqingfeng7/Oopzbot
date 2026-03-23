    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setStatus(text, variant, "setupState");
    }

    function escapeHtml(value) {
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function levelClass(level) {
      if (level === "fail") {
        return "danger";
      }
      if (level === "warn") {
        return "warning";
      }
      if (level === "pass") {
        return "success";
      }
      return "neutral";
    }

    function levelText(level) {
      if (level === "fail") {
        return "失败";
      }
      if (level === "warn") {
        return "警告";
      }
      if (level === "pass") {
        return "通过";
      }
      return "信息";
    }

    function stepText(status) {
      if (status === "blocked") {
        return "阻塞";
      }
      if (status === "pending") {
        return "待处理";
      }
      if (status === "done") {
        return "已完成";
      }
      return "可选";
    }

    function openAdminPage(path) {
      if (!path) {
        return;
      }
      window.location.href = path;
    }

    function renderWizard(steps) {
      const root = AdminShell.byId("wizardList");
      if (!root) {
        return;
      }
      const items = Array.isArray(steps) ? steps : [];
      if (!items.length) {
        root.innerHTML = '<div class="empty-state">暂无向导步骤</div>';
        return;
      }
      root.innerHTML = items.map((step, index) => {
        const action = step.actions && step.actions.length ? escapeHtml(step.actions[0]) : "当前无需额外操作";
        const page = step.page || "";
        const button = page
          ? `<button class="btn btn-ghost" type="button" onclick="openAdminPage('${escapeHtml(page)}')">打开页面</button>`
          : "";
        return `
          <article class="surface-card">
            <div class="section-head">
              <div>
                <p class="section-eyebrow">STEP ${index + 1}</p>
                <h3 class="section-title">${escapeHtml(step.title || "")}</h3>
              </div>
              <span class="status-text is-${levelClass(step.status === "blocked" ? "fail" : (step.status === "pending" ? "warn" : (step.status === "done" ? "pass" : "info")))}">${stepText(step.status)}</span>
            </div>
            <div class="stack">
              <div>${escapeHtml(step.description || "")}</div>
              <div>当前状态: ${escapeHtml(step.summary || "")}</div>
              <div>建议操作: ${action}</div>
              <div class="action-row">${button}</div>
            </div>
          </article>
        `;
      }).join("");
    }

    function renderChecks(checks) {
      const root = AdminShell.byId("checkRows");
      if (!root) {
        return;
      }
      const items = Array.isArray(checks) ? checks : [];
      if (!items.length) {
        root.innerHTML = '<tr><td colspan="4" class="empty-state">暂无体检结果</td></tr>';
        return;
      }
      root.innerHTML = items.map((item) => {
        const button = item.page
          ? `<button class="btn btn-ghost btn-sm" type="button" onclick="openAdminPage('${escapeHtml(item.page)}')">打开</button>`
          : "";
        return `
          <tr>
            <td><span class="status-text is-${levelClass(item.level)}">${levelText(item.level)}</span></td>
            <td>${escapeHtml(item.title || "")}</td>
            <td>${escapeHtml(item.summary || item.detail || "")}</td>
            <td>
              <div>${escapeHtml(item.action || "无需操作")}</div>
              <div style="margin-top: 8px;">${button}</div>
            </td>
          </tr>
        `;
      }).join("");
    }

    function renderDiagnostics(data) {
      const summary = data.summary || {};
      const statusMap = {
        pass: "正常",
        warn: "需关注",
        fail: "存在阻塞项",
      };
      const overall = data.status || "warn";
      AdminShell.byId("setupOverall").textContent = statusMap[overall] || "已生成";
      AdminShell.animateNumber("setupPass", Number(summary.pass || 0));
      AdminShell.animateNumber("setupWarn", Number(summary.warn || 0));
      AdminShell.animateNumber("setupFail", Number(summary.fail || 0));
      AdminShell.animateNumber("setupInfo", Number(summary.info || 0));
      renderWizard(data.wizard_steps || []);
      renderChecks(data.checks || []);
      setPageState("体检已完成", overall === "fail" ? "error" : (overall === "warn" ? "warning" : "success"));
    }

    async function loadDiagnostics() {
      const data = await AdminShell.req("/admin/api/setup/diagnostics");
      renderDiagnostics(data);
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录体检页",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadDiagnostics();
      } catch (_) {
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        AdminShell.showMessage("loginMsg", "");
        setPageState("等待体检", "warning");
      }
    }

    async function login() {
      try {
        await AdminShell.req("/admin/api/login", {
          method: "POST",
          body: JSON.stringify({ password: AdminShell.byId("pwd").value || "" }),
        });
        AdminShell.showMessage("loginMsg", "登录成功");
        await check();
      } catch (error) {
        AdminShell.showMessage("loginMsg", error.message, true);
        setPageState("登录失败", "error");
      }
    }

    async function logout() {
      try {
        await AdminShell.req("/admin/api/logout", { method: "POST", body: "{}" });
      } catch (_) {
      }
      await check();
    }

    AdminShell.init({ page: "setup", passwordHandler: login });
    check();
