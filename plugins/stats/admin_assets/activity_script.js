    let dailyChartInstance = null;
    let rankingChartInstance = null;
    let chartJsLoaded = false;

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setMicroStatus(text, variant, "activityState");
    }

    var escapeHtml = AdminShell.escapeHtml;

    // ---- 统计接口参数（集中配置，避免散落魔法数字）----
    var STATS = {
      trendDays: 14,
      rankingDays: 7,
      rankingLimit: 10,
    };

    // 名次奖牌配色：前三名金/银/铜，其余走灰色圆环
    var MEDAL_PALETTE = [
      { fill: "#fbbf24", ring: "#f59e0b" },
      { fill: "#cbd5e1", ring: "#94a3b8" },
      { fill: "#d99a5b", ring: "#b45309" },
    ];

    // 排行柱状图配色循环
    var BAR_COLORS = [
      "#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#d946ef",
      "#ec4899", "#f43f5e", "#f97316", "#eab308", "#22c55e",
    ];

    // 称号档位表：按 min 降序，命中第一个 total >= min 的档位即可。
    // 新增/调整称号只改这张表，icon 取 ICON 库的键名。
    var RANK_TITLES = [
      { min: 1000, label: "宇宙级话痨", color: "#a855f7", icon: "crown" },
      { min: 200, label: "群聊永动机", color: "#8b5cf6", icon: "crown" },
      { min: 100, label: "话痨之王", color: "#6366f1", icon: "crown" },
      { min: 50, label: "社交牛逼症", color: "#f97316", icon: "flame" },
      { min: 20, label: "活跃分子", color: "#eab308", icon: "bolt" },
      { min: 5, label: "冒泡选手", color: "#22c55e", icon: "chat" },
      { min: 1, label: "潜水偷看", color: "#38bdf8", icon: "drop" },
      { min: 0, label: "查无此人", color: "#94a3b8", icon: "ghost" },
    ];

    // 统一的用户展示名回退：优先 display_name，其次截断 user_id
    function displayName(row, maxLen) {
      return row.display_name || (row.user_id || "").slice(0, maxLen || 8);
    }

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

    // ---- SVG 图标库（全部内联，不用 emoji）----
    var ICON = {
      crown: '<path d="M3 7l4 4 5-7 5 7 4-4-2 12H5L3 7z"/>',
      flame: '<path d="M12 2c1 4-2 5-2 8a2 2 0 104 0c0-1 0-2-1-3 3 1 4 4 4 7a5 5 0 11-10 0c0-4 3-6 5-12z"/>',
      bolt: '<path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"/>',
      chat: '<path d="M4 4h16v12H7l-3 3V4z"/>',
      drop: '<path d="M12 3s6 7 6 11a6 6 0 11-12 0c0-4 6-11 6-11z"/>',
      ghost:
        '<path d="M5 21V10a7 7 0 0114 0v11l-2.5-1.8L14 21l-2-1.8L10 21l-2.5-1.8L5 21z"/>' +
        '<circle cx="9.5" cy="10.5" r="1.2" fill="#0f172a"/>' +
        '<circle cx="14.5" cy="10.5" r="1.2" fill="#0f172a"/>',
    };

    function iconSvg(path, color) {
      return (
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="' + color +
        '" aria-hidden="true" style="vertical-align:-2px;margin-right:5px;">' + path + "</svg>"
      );
    }

    // 按消息数命中称号档位（数据驱动，档位见 RANK_TITLES）
    function titleMeta(total) {
      var n = Number(total) || 0;
      for (var i = 0; i < RANK_TITLES.length; i++) {
        if (n >= RANK_TITLES[i].min) return RANK_TITLES[i];
      }
      return RANK_TITLES[RANK_TITLES.length - 1];
    }

    // 名次徽章：前三名金/银/铜奖牌 SVG，其余编号圆环
    function rankBadgeSvg(index) {
      if (index < MEDAL_PALETTE.length) {
        var c = MEDAL_PALETTE[index];
        return (
          '<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">' +
            '<path d="M8 2l2 5h4l2-5" fill="none" stroke="' + c.ring + '" stroke-width="2" stroke-linecap="round"/>' +
            '<circle cx="12" cy="14" r="7" fill="' + c.fill + '" stroke="' + c.ring + '" stroke-width="2"/>' +
            '<text x="12" y="17.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#1f2937">' +
              (index + 1) + "</text>" +
          "</svg>"
        );
      }
      return (
        '<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">' +
          '<circle cx="12" cy="12" r="9" fill="rgba(148,163,184,0.16)" stroke="rgba(148,163,184,0.5)" stroke-width="1.5"/>' +
          '<text x="12" y="15.5" text-anchor="middle" font-size="9" font-weight="700" fill="#cbd5e1">' +
            (index + 1) + "</text>" +
        "</svg>"
      );
    }

    function crownSvg() {
      return (
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="#fbbf24" aria-hidden="true" ' +
        'style="vertical-align:-2px;margin-left:5px;"><path d="M3 7l4 4 5-7 5 7 4-4-2 12H5L3 7z"/></svg>'
      );
    }

    function renderRankingChart(ranking) {
      var labels = ranking.map(function (r, i) {
        return "#" + (i + 1) + " " + displayName(r);
      });
      var data = ranking.map(function (r) { return r.total; });
      var ctx = document.getElementById("rankingChart");
      if (!ctx) return;

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
            backgroundColor: BAR_COLORS.slice(0, data.length),
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
        var crown = i === 0 ? crownSvg() : "";
        var meta = titleMeta(r.total);
        var pill =
          '<span class="rank-title" style="--title-color:' + meta.color + ';">' +
            iconSvg(ICON[meta.icon], meta.color) + escapeHtml(meta.label) + "</span>";
        return (
          "<tr>" +
            '<td>' + rankBadgeSvg(i) + "</td>" +
            '<td class="table-emphasis">' + escapeHtml(displayName(r, 12)) + crown + "</td>" +
            "<td>" + escapeHtml(r.total) + "</td>" +
            "<td>" + pill + "</td>" +
          "</tr>"
        );
      }).join("");
      AdminShell.byId("rankingRows").innerHTML = rows || emptyRankingRow();
    }

    function emptyRankingRow() {
      var svg =
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" style="vertical-align:-4px;margin-right:6px;">' +
          '<path d="M4 5h16v10H8l-4 4V5z"/>' +
          '<circle cx="9" cy="10" r="1" fill="currentColor"/>' +
          '<circle cx="12" cy="10" r="1" fill="currentColor"/>' +
          '<circle cx="15" cy="10" r="1" fill="currentColor"/>' +
        "</svg>";
      return '<tr><td colspan="4" class="empty-state">' + svg + "还没人冒泡，快去群里水两句</td></tr>";
    }

    async function loadActivity() {
      await loadChartJs();

      var [overview, dailyData, rankingData] = await Promise.all([
        AdminShell.req("/admin/api/message-stats/overview"),
        AdminShell.req("/admin/api/message-stats/daily?days=" + STATS.trendDays),
        AdminShell.req(
          "/admin/api/message-stats/ranking?days=" + STATS.rankingDays + "&limit=" + STATS.rankingLimit
        ),
      ]);

      AdminShell.animateNumber("todayMsgValue", overview.today_messages || 0);
      AdminShell.animateNumber("weekMsgValue", overview.week_messages || 0);
      AdminShell.animateNumber("activeUsersValue", overview.active_users_today || 0);

      renderDailyChart(dailyData.daily || []);

      var ranking = rankingData.ranking || [];
      renderRankingChart(ranking);
      renderRankingTable(ranking);

      var champ = ranking.length ? displayName(ranking[0]) : "";
      setPageState(champ ? ("本期榜首：" + champ) : "战绩已刷新", "success");
    }

    AdminShell.registerActions({
      "refresh-activity": () => loadActivity(),
    });
    AdminShell.bootstrapAuth({
      page: "activity",
      loggedInText: "已登录活跃统计",
      loginSuccessMessage: null,
      onLogin: () => loadActivity(),
      onLoggedOut: () => setPageState("等待同步", "warning"),
      onLoginError: () => setPageState("登录失败", "error"),
    });
