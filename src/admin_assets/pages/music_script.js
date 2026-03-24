    let searchResults = [];
    let searchPage = 1;
    let searchPages = 1;
    let searchKeyword = "";
    let queuePage = 1;
    let queuePages = 1;

    var escapeHtml = AdminShell.escapeHtml;

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
    }

    function setControlState(text, variant) {
      AdminShell.setMicroStatus(text, variant, "ctlState");
      setPageState(text, variant);
    }

    function renderMusicArea(info) {
      const area = info.area || "-";
      const defaultArea = info.default_area || "-";
      const activeArea = info.active_area || "-";
      const sourceText = info.source_text || "未解析";
      let variant = "warning";
      if (info.source === "active" || info.source === "default") {
        variant = "success";
      } else if (info.source === "auto") {
        variant = "warning";
      } else if (info.source === "none") {
        variant = "error";
      }
      AdminShell.setMicroStatus("来源：" + sourceText, variant, "musicAreaState");
      AdminShell.byId("musicAreaText").textContent = "当前音乐域：" + area;
      AdminShell.byId("musicDefaultAreaText").textContent = "默认域：" + defaultArea;
      AdminShell.byId("musicActiveAreaText").textContent = "活跃域：" + activeArea;
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录音乐页",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadQueue();
        if (searchKeyword) {
          await searchSongs(false);
        }
      } catch (_) {
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        AdminShell.showMessage("loginMsg", "");
        AdminShell.setMicroStatus("等待操作", "neutral", "ctlState");
        renderMusicArea({});
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

    async function control(action) {
      try {
        await AdminShell.req("/admin/api/control", {
          method: "POST",
          body: JSON.stringify({ action }),
        });
        AdminShell.showMessage("ctlMsg", "操作成功：" + action);
        setControlState("播放器状态已更新", "success");
        await loadQueue();
      } catch (error) {
        AdminShell.showMessage("ctlMsg", error.message, true);
        setControlState("播放控制失败", "error");
      }
    }

    async function clearQueue() {
      try {
        await AdminShell.req("/admin/api/queue/clear", { method: "POST", body: "{}" });
        AdminShell.showMessage("ctlMsg", "队列已清空");
        setControlState("队列已清空", "warning");
        await loadQueue();
      } catch (error) {
        AdminShell.showMessage("ctlMsg", error.message, true);
      }
    }

    async function loadQueue() {
      const data = await AdminShell.req("/admin/api/queue?page=" + queuePage + "&page_size=10");
      const rows = [];
      renderMusicArea(data.music_area || {});

      if (data.current) {
        rows.push(
          '<tr class="table-row--current">' +
            "<td>NOW</td>" +
            '<td class="table-emphasis">' + escapeHtml(data.current.name || "-") + "</td>" +
            "<td>" + escapeHtml(data.current.artists || "-") + "</td>" +
            "<td>" + escapeHtml(data.current.durationText || "-") + "</td>" +
            '<td><span class="badge-soft">当前播放</span></td>' +
          "</tr>"
        );
      }

      (data.queue || []).forEach((item) => {
        rows.push(
          "<tr>" +
            "<td>" + (item.index ?? "-") + "</td>" +
            "<td>" + escapeHtml(item.name || "-") + "</td>" +
            "<td>" + escapeHtml(item.artists || "-") + "</td>" +
            "<td>" + escapeHtml(item.durationText || "-") + "</td>" +
            "<td>" +
              '<div class="action-row">' +
                '<button class="btn btn-sm btn-ghost" type="button" onclick="queueAction(\'top\', ' + item.index + ')">置顶</button>' +
                '<button class="btn btn-sm btn-danger" type="button" onclick="queueAction(\'remove\', ' + item.index + ')">删除</button>' +
              "</div>" +
            "</td>" +
          "</tr>"
        );
      });

      AdminShell.byId("queueRows").innerHTML = rows.join("") || '<tr><td colspan="5" class="empty-state">当前队列为空</td></tr>';
      queuePage = data.page || 1;
      queuePages = data.pages || 1;
      AdminShell.byId("queueInfo").textContent = "第 " + queuePage + "/" + queuePages + " 页，共 " + (data.total || 0) + " 首";
      setPageState("队列已同步", "success");
    }

    async function queueAction(action, index) {
      try {
        await AdminShell.req("/admin/api/queue/action", {
          method: "POST",
          body: JSON.stringify({ action, index }),
        });
        AdminShell.showMessage("queueMsg", "队列操作成功");
        await loadQueue();
      } catch (error) {
        AdminShell.showMessage("queueMsg", error.message, true);
      }
    }

    function changeQueue(delta) {
      const next = queuePage + delta;
      if (next < 1 || next > queuePages) {
        return;
      }
      queuePage = next;
      loadQueue().catch(() => {});
    }

    async function searchSongs(reset) {
      if (reset) {
        searchPage = 1;
        searchKeyword = (AdminShell.byId("kw").value || "").trim();
      }
      if (!searchKeyword) {
        AdminShell.byId("searchRows").innerHTML = '<tr><td colspan="4" class="empty-state">请输入关键词后再搜索</td></tr>';
        AdminShell.byId("searchInfo").textContent = "";
        AdminShell.showMessage("searchMsg", "请输入关键词", true);
        return;
      }
      try {
        const data = await AdminShell.req(
          "/admin/api/search?keyword=" + encodeURIComponent(searchKeyword) + "&page=" + searchPage + "&page_size=10"
        );
        searchResults = data.results || [];
        AdminShell.byId("searchRows").innerHTML =
          searchResults
            .map((item, index) => {
              return (
                "<tr>" +
                  "<td>" + escapeHtml(item.name || "-") + "</td>" +
                  "<td>" + escapeHtml(item.artists || "-") + "</td>" +
                  "<td>" + escapeHtml(item.album || "-") + "</td>" +
                  '<td><button class="btn btn-sm btn-primary" type="button" onclick="addSong(' + index + ')">加入队列</button></td>' +
                "</tr>"
              );
            })
            .join("") || '<tr><td colspan="4" class="empty-state">没有找到相关歌曲</td></tr>';
        searchPage = data.page || 1;
        searchPages = data.pages || 1;
        AdminShell.byId("searchInfo").textContent = "第 " + searchPage + "/" + searchPages + " 页，共 " + (data.total || 0) + " 条";
        AdminShell.showMessage("searchMsg", "搜索完成");
      } catch (error) {
        AdminShell.showMessage("searchMsg", error.message, true);
      }
    }

    function changeSearch(delta) {
      const next = searchPage + delta;
      if (next < 1 || next > searchPages) {
        return;
      }
      searchPage = next;
      searchSongs(false).catch(() => {});
    }

    async function addSong(index) {
      try {
        const song = searchResults[index];
        if (!song || !song.id) {
          throw new Error("歌曲数据无效，请重新搜索");
        }
        const data = await AdminShell.req("/admin/api/add", {
          method: "POST",
          body: JSON.stringify(song),
        });
        AdminShell.showMessage("searchMsg", "已加入队列：" + (data.name || song.name) + "（位置 " + (data.position ?? "-") + "）");
        await loadQueue();
      } catch (error) {
        AdminShell.showMessage("searchMsg", error.message, true);
      }
    }

    AdminShell.init({ page: "music", passwordHandler: login });
    check();
