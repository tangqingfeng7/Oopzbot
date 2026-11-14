    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
    }

    function formatScreenShareTime(timestamp) {
      if (!timestamp) return "-";
      return new Date(Number(timestamp) * 1000).toLocaleString("zh-CN", { hour12: false });
    }

    function formatRemaining(expiresAt) {
      const seconds = Math.max(0, Number(expiresAt || 0) - Math.floor(Date.now() / 1000));
      if (seconds < 60) return seconds + " 秒";
      const minutes = Math.floor(seconds / 60);
      if (minutes < 60) return minutes + " 分钟";
      return Math.floor(minutes / 60) + " 小时 " + (minutes % 60) + " 分钟";
    }

    async function loadScreenShares() {
      const root = AdminShell.byId("screenShareSessions");
      root.innerHTML = '<div class="empty-state">正在读取共享状态...</div>';
      setPageState("正在同步", "warning");
      try {
        const data = await AdminShell.req("/admin/api/screen-shares");
        const shares = Array.isArray(data.shares) ? data.shares : [];
        AdminShell.byId("screenShareCount").textContent = String(shares.length);
        if (!shares.length) {
          root.innerHTML = '<div class="empty-state">当前没有正在进行的屏幕共享</div>';
          setPageState("暂无活动共享", "success");
          return;
        }
        root.innerHTML = shares.map(function(share, index) {
          const linkId = "screenShareLink_" + index;
          const areaName = share.area_name || share.area;
          const channelName = share.channel_name || share.channel;
          const presenterName = share.presenter_name || share.presenter_uid;
          return '<div class="ss-admin-row">' +
            '<div class="ss-admin-summary"><div><div class="ss-admin-title"><span class="ss-admin-dot"></span>' + AdminShell.escapeHtml(channelName) + '</div>' +
            '<div class="ss-admin-meta"><span title="' + AdminShell.escapeHtml(share.area) + '">域：' + AdminShell.escapeHtml(areaName) + '</span><span title="' + AdminShell.escapeHtml(share.channel) + '">频道：' + AdminShell.escapeHtml(channelName) + '</span><span title="' + AdminShell.escapeHtml(share.presenter_uid) + '">发起者：' + AdminShell.escapeHtml(presenterName) + '</span></div></div>' +
            '<span class="ss-admin-time">开始于 ' + AdminShell.escapeHtml(formatScreenShareTime(share.ready_at)) + ' · 剩余 ' + AdminShell.escapeHtml(formatRemaining(share.expires_at)) + '</span></div>' +
            '<div class="ss-admin-link"><input id="' + linkId + '" type="text" readonly value="' + AdminShell.escapeHtml(share.viewer_url) + '" />' +
            '<button class="btn btn-sm btn-ghost" type="button" data-action="copy-screen-share-link" data-link-id="' + linkId + '">复制</button>' +
            '<a class="btn btn-sm btn-primary" href="' + AdminShell.escapeHtml(share.viewer_url) + '" target="_blank" rel="noopener noreferrer">打开</a>' +
            '<button class="btn btn-sm btn-danger" type="button" data-action="stop-screen-share" data-session-id="' + AdminShell.escapeHtml(share.id) + '" data-presenter-name="' + AdminShell.escapeHtml(presenterName) + '" data-channel-name="' + AdminShell.escapeHtml(channelName) + '">结束共享</button></div></div>';
        }).join("");
        setPageState("活动共享 " + shares.length + " 个", "success");
      } catch (error) {
        root.innerHTML = '<div class="empty-state">读取失败：' + AdminShell.escapeHtml(error.message || String(error)) + '</div>';
        setPageState("读取失败", "error");
      }
    }

    async function copyScreenShareLink(element) {
      const input = AdminShell.byId(element.dataset.linkId);
      if (!input || !input.value) return;
      try {
        await AdminShell.copyText(input.value);
        AdminShell.showMessage("screenShareMsg", "观看链接已复制");
      } catch (_) {
        AdminShell.showMessage("screenShareMsg", "复制失败，请手动复制", true);
      }
    }

    async function stopScreenShare(element) {
      const sessionId = element.dataset.sessionId || "";
      if (!sessionId) return;
      const presenterName = element.dataset.presenterName || "该用户";
      const channelName = element.dataset.channelName || "该频道";
      const confirmed = await AdminShell.confirm(
        "结束屏幕共享",
        "确认结束 <strong>" + AdminShell.escapeHtml(presenterName) + "</strong> 在「" + AdminShell.escapeHtml(channelName) + "」的屏幕共享？",
        { okText: "结束共享" },
      );
      if (!confirmed) return;

      element.disabled = true;
      element.textContent = "正在结束...";
      try {
        const data = await AdminShell.req(
          "/admin/api/screen-shares/" + encodeURIComponent(sessionId) + "/stop",
          { method: "POST", body: "{}" },
        );
        AdminShell.showMessage("screenShareMsg", data.message || "屏幕共享已结束");
        await loadScreenShares();
      } catch (error) {
        element.disabled = false;
        element.textContent = "结束共享";
        AdminShell.showMessage("screenShareMsg", "结束失败：" + (error.message || String(error)), true);
        setPageState("结束失败", "error");
      }
    }

    AdminShell.registerActions({
      "refresh-screen-shares": () => loadScreenShares(),
      "copy-screen-share-link": (el) => copyScreenShareLink(el),
      "stop-screen-share": (el) => stopScreenShare(el),
    });
    AdminShell.bootstrapAuth({
      page: "screen-share",
      loggedInText: "已登录屏幕共享页",
      onLogin: () => loadScreenShares(),
      onLoggedOut: () => setPageState("等待操作", "warning"),
      onLoginError: () => setPageState("登录失败", "error"),
    });
