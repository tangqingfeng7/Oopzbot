    let logPollTimer = null;
    let logTailSize = 200;
    let logBusy = false;

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setStatus(text, variant, "logState");
    }

    function stopLogPolling() {
      if (logPollTimer) {
        clearInterval(logPollTimer);
        logPollTimer = null;
      }
      const panel = AdminShell.byId("panel");
      if (!panel || panel.classList.contains("hidden")) {
        return;
      }
      setPageState("日志轮询已暂停", "warning");
    }

    function startLogPolling() {
      const panel = AdminShell.byId("panel");
      if (!panel || panel.classList.contains("hidden")) {
        return;
      }
      stopLogPolling();
      setPageState("日志轮询中", "success");
      logPollTimer = setInterval(() => {
        loadLogs(logTailSize).catch(() => {});
      }, 2000);
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录系统页",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await Promise.all([loadLink(), loadSys(), loadLogs(logTailSize)]);
        startLogPolling();
      } catch (_) {
        stopLogPolling();
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        AdminShell.showMessage("loginMsg", "");
        setPageState("等待轮询", "warning");
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

    async function loadLink() {
      const data = await AdminShell.req("/admin/api/player/link");
      AdminShell.byId("playerLink").value = data.url || "";
      AdminShell.flashUpdate("playerLink");
    }

    async function rotateLink() {
      try {
        const data = await AdminShell.req("/admin/api/player/link/rotate", { method: "POST", body: "{}" });
        AdminShell.byId("playerLink").value = data.url || "";
        AdminShell.showMessage("linkMsg", "播放器链接已重置");
      } catch (error) {
        AdminShell.showMessage("linkMsg", error.message, true);
      }
    }

    async function copyLink() {
      const value = AdminShell.byId("playerLink").value || "";
      if (!value) {
        AdminShell.showMessage("linkMsg", "当前没有可复制的链接", true);
        return;
      }
      try {
        await AdminShell.copyText(value);
        AdminShell.showMessage("linkMsg", "链接已复制到剪贴板");
      } catch (_) {
        AdminShell.showMessage("linkMsg", "复制失败，请手动复制", true);
      }
    }

    async function loadSys() {
      const data = await AdminShell.req("/admin/api/system");
      AdminShell.byId("sys").textContent = JSON.stringify(data, null, 2);
      setPageState("系统信息已同步", "success");
    }

    async function loadLogs(lines) {
      logTailSize = lines || logTailSize;
      if (logBusy) {
        return;
      }
      logBusy = true;
      try {
        const logsElement = AdminShell.byId("logs");
        const stickBottom = logsElement.scrollTop + logsElement.clientHeight >= logsElement.scrollHeight - 8;
        const data = await AdminShell.req("/admin/api/logs?tail=" + logTailSize);
        const content = (data.lines || data.logs || []).join("\n") || "-";
        logsElement.textContent = content;
        if (stickBottom) {
          logsElement.scrollTop = logsElement.scrollHeight;
        }
        setPageState("日志轮询中", "success");
      } finally {
        logBusy = false;
      }
    }

    AdminShell.init({ page: "system", passwordHandler: login });
    check();

    document.addEventListener("visibilitychange", () => {
      const panel = AdminShell.byId("panel");
      if (!panel || panel.classList.contains("hidden")) {
        return;
      }
      if (document.hidden) {
        stopLogPolling();
      } else {
        startLogPolling();
      }
    });

    window.addEventListener("beforeunload", stopLogPolling);
