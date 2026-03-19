    let overviewStream = null;
    let overviewReconnectTimer = null;

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
    }

    function setLiveState(text, variant) {
      AdminShell.setMicroStatus(text, variant, "overviewLiveHint");
      setPageState(text, variant);
    }

    function renderOverview(data) {
      const redis = data.redis || "-";
      const redisElement = AdminShell.byId("sRedis");
      if (redisElement) {
        redisElement.textContent = redis;
        redisElement.dataset.value = redis;
      }
      AdminShell.animateNumber("sUp", Number(data.uptime_seconds ?? 0));
      AdminShell.animateNumber("sQueue", Number(data.queue_length ?? 0));
      AdminShell.animateNumber("sTotal", Number(data.statistics_summary?.total_plays ?? 0));
      AdminShell.animateNumber("sTodayMsg", Number(data.today_messages ?? 0));
      AdminShell.animateNumber("sActiveUsers", Number(data.active_users_today ?? 0));
      AdminShell.flashUpdate("sRedis");
    }

    async function loadOverview() {
      const data = await AdminShell.req("/admin/api/overview");
      renderOverview(data);
      setLiveState("概览已同步", "success");
    }

    function stopOverviewStream() {
      if (overviewReconnectTimer) {
        clearTimeout(overviewReconnectTimer);
        overviewReconnectTimer = null;
      }
      if (overviewStream) {
        overviewStream.close();
        overviewStream = null;
      }
      const panel = AdminShell.byId("panel");
      if (!panel || panel.classList.contains("hidden")) {
        return;
      }
      setLiveState("实时流已暂停", "warning");
    }

    function startOverviewStream() {
      const panel = AdminShell.byId("panel");
      if (!panel || panel.classList.contains("hidden")) {
        return;
      }
      stopOverviewStream();
      setLiveState("正在连接实时流", "warning");

      const connect = () => {
        overviewStream = new EventSource("/admin/api/overview/stream", { withCredentials: true });
        overviewStream.addEventListener("overview", (event) => {
          try {
            renderOverview(JSON.parse(event.data || "{}"));
            setLiveState("实时连接中", "success");
          } catch (_) {
            setLiveState("实时数据解析失败", "error");
          }
        });
        overviewStream.onerror = () => {
          if (overviewStream) {
            overviewStream.close();
            overviewStream = null;
          }
          setLiveState("实时流重连中", "warning");
          if (overviewReconnectTimer) {
            clearTimeout(overviewReconnectTimer);
          }
          overviewReconnectTimer = setTimeout(connect, 1200);
        };
      };

      connect();
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录总览",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadOverview();
        startOverviewStream();
      } catch (_) {
        stopOverviewStream();
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        AdminShell.showMessage("loginMsg", "");
        AdminShell.setMicroStatus("等待连接", "warning", "overviewLiveHint");
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
        setLiveState("登录失败", "error");
      }
    }

    async function logout() {
      try {
        await AdminShell.req("/admin/api/logout", { method: "POST", body: "{}" });
      } catch (_) {
      }
      await check();
    }

    AdminShell.init({ page: "dashboard", passwordHandler: login });
    check();

    document.addEventListener("visibilitychange", () => {
      const panel = AdminShell.byId("panel");
      if (!panel || panel.classList.contains("hidden")) {
        return;
      }
      if (document.hidden) {
        stopOverviewStream();
      } else {
        startOverviewStream();
      }
    });

    window.addEventListener("beforeunload", stopOverviewStream);
