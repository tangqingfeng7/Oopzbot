    let dailyChartInstance = null;
    let rankingChartInstance = null;
    let chartJsLoaded = false;

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setMicroStatus(text, variant, "activityState");
    }

    var escapeHtml = AdminShell.escapeHtml;

    function loadChartJs() {
      if (chartJsLoaded) return Promise.resolve();
      return new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js";
        script.onload = function () {
          chartJsLoaded = true;
          resolve();
        };
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }

    function renderDailyChart(daily) {
      var labels = daily.map(function (d) { return d.date.slice(5); });
      var data = daily.map(function (d) { return d.total; });
      var ctx = document.getElementById("dailyChart");
      if (!ctx) return;

      if (dailyChartInstance) {
        dailyChartInstance.data.labels = labels;
        dailyChartInstance.data.datasets[0].data = data;
        dailyChartInstance.update();
        return;
      }

      var gradient = ctx.getContext("2d").createLinearGradient(0, 0, 0, 260);
      gradient.addColorStop(0, "rgba(59, 130, 246, 0.25)");
      gradient.addColorStop(1, "rgba(59, 130, 246, 0.02)");

      dailyChartInstance = new Chart(ctx, {
        type: "line",
        data: {
          labels: labels,
          datasets: [{
            label: "消息数",
            data: data,
            borderColor: "#3b82f6",
            backgroundColor: gradient,
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 5,
            tension: 0.3,
            fill: true,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
          },
          scales: {
            x: {
              grid: { color: "rgba(255,255,255,0.06)" },
              ticks: { color: "#94a3b8", font: { size: 11 } },
            },
            y: {
              beginAtZero: true,
              grid: { color: "rgba(255,255,255,0.06)" },
              ticks: { color: "#94a3b8", font: { size: 11 }, precision: 0 },
            },
          },
        },
      });
    }

    function renderRankingChart(ranking) {
      var labels = ranking.map(function (r) { return r.display_name || r.user_id.slice(0, 8); });
      var data = ranking.map(function (r) { return r.total; });
      var ctx = document.getElementById("rankingChart");
      if (!ctx) return;

      var colors = [
        "#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#d946ef",
        "#ec4899", "#f43f5e", "#f97316", "#eab308", "#22c55e",
      ];

      if (rankingChartInstance) {
        rankingChartInstance.data.labels = labels;
        rankingChartInstance.data.datasets[0].data = data;
        rankingChartInstance.update();
        return;
      }

      rankingChartInstance = new Chart(ctx, {
        type: "bar",
        data: {
          labels: labels,
          datasets: [{
            label: "消息数",
            data: data,
            backgroundColor: colors.slice(0, data.length),
            borderRadius: 4,
            barPercentage: 0.65,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: "y",
          plugins: {
            legend: { display: false },
          },
          scales: {
            x: {
              beginAtZero: true,
              grid: { color: "rgba(255,255,255,0.06)" },
              ticks: { color: "#94a3b8", font: { size: 11 }, precision: 0 },
            },
            y: {
              grid: { display: false },
              ticks: { color: "#94a3b8", font: { size: 11 } },
            },
          },
        },
      });
    }

    function renderRankingTable(ranking) {
      var rows = ranking.map(function (r, i) {
        var prefix = i + 1;
        return (
          "<tr>" +
            "<td>" + prefix + "</td>" +
            '<td class="table-emphasis">' + escapeHtml(r.display_name || r.user_id.slice(0, 12)) + "</td>" +
            "<td>" + escapeHtml(r.total) + "</td>" +
          "</tr>"
        );
      }).join("");
      AdminShell.byId("rankingRows").innerHTML =
        rows || '<tr><td colspan="3" class="empty-state">暂无数据</td></tr>';
    }

    async function loadActivity() {
      await loadChartJs();

      var [overview, dailyData, rankingData] = await Promise.all([
        AdminShell.req("/admin/api/message-stats/overview"),
        AdminShell.req("/admin/api/message-stats/daily?days=14"),
        AdminShell.req("/admin/api/message-stats/ranking?days=7&limit=10"),
      ]);

      AdminShell.animateNumber("todayMsgValue", overview.today_messages || 0);
      AdminShell.animateNumber("weekMsgValue", overview.week_messages || 0);
      AdminShell.animateNumber("activeUsersValue", overview.active_users_today || 0);

      renderDailyChart(dailyData.daily || []);

      var ranking = rankingData.ranking || [];
      renderRankingChart(ranking);
      renderRankingTable(ranking);

      setPageState("统计已同步", "success");
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录活跃统计",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadActivity();
      } catch (_) {
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        setPageState("等待同步", "warning");
      }
    }

    async function login() {
      try {
        await AdminShell.req("/admin/api/login", {
          method: "POST",
          body: JSON.stringify({ password: AdminShell.byId("pwd").value || "" }),
        });
        await check();
      } catch (error) {
        AdminShell.showMessage("loginMsg", error.message, true);
        setPageState("登录失败", "error");
      }
    }

    async function logout() {
      try {
        await AdminShell.req("/admin/api/logout", { method: "POST", body: "{}" });
      } catch (_) {}
      await check();
    }

    AdminShell.init({ page: "activity", passwordHandler: login });
    check();
