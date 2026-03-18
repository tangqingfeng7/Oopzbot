    let topPage = 1;
    let topPages = 1;

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setMicroStatus(text, variant, "statsState");
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录统计页",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadTop();
      } catch (_) {
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        AdminShell.showMessage("loginMsg", "");
        setPageState("等待同步", "warning");
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

    async function loadTop() {
      const data = await AdminShell.req("/admin/api/statistics?days=7&top_page=" + topPage + "&top_page_size=12");
      const rows = (data.top_songs || [])
        .map((item) => {
          return (
            "<tr>" +
              '<td class="table-emphasis">' + escapeHtml(item.song_name || "-") + "</td>" +
              "<td>" + escapeHtml(item.artist || "-") + "</td>" +
              "<td>" + escapeHtml(item.play_count || 0) + "</td>" +
              "<td>" + escapeHtml(item.last_played_at || "-") + "</td>" +
            "</tr>"
          );
        })
        .join("");

      AdminShell.byId("topRows").innerHTML = rows || '<tr><td colspan="4" class="empty-state">暂无统计数据</td></tr>';
      topPage = data.top_page || 1;
      topPages = data.top_pages || 1;

      const leaderCount = data.top_songs && data.top_songs.length ? Number(data.top_songs[0].play_count || 0) : 0;
      AdminShell.animateNumber("topTotalValue", Number(data.top_total || 0));
      AdminShell.byId("topPageValue").textContent = topPage + " / " + topPages;
      AdminShell.byId("topPageValue").dataset.value = topPage;
      AdminShell.animateNumber("leaderCountValue", leaderCount);
      AdminShell.byId("topInfo").textContent = "第 " + topPage + "/" + topPages + " 页，共 " + (data.top_total || 0) + " 首";
      setPageState("统计已同步", "success");
    }

    function changeTop(delta) {
      const next = topPage + delta;
      if (next < 1 || next > topPages) {
        return;
      }
      topPage = next;
      loadTop().catch(() => {});
    }

    async function clearHistory() {
      try {
        const data = await AdminShell.req("/admin/api/statistics/clear_history", { method: "POST", body: "{}" });
        AdminShell.showMessage("msg", "已清理播放历史 " + (data.deleted || 0) + " 条");
        setPageState("历史已清空", "warning");
        await loadTop();
      } catch (error) {
        AdminShell.showMessage("msg", error.message, true);
      }
    }

    AdminShell.init({ page: "stats", passwordHandler: login });
    check();
