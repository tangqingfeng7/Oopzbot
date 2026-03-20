    var currentOffset = 0;
    var pageSize = 50;
    var totalMembers = 0;
    var _modalResolve = null;
    var currentArea = "";

    function getArea() { return currentArea; }

    async function loadAreas() {
      try {
        var data = await AdminShell.req("/admin/api/areas");
        var areas = data.areas || [];
        var picker = AdminShell.byId("areaPicker");
        picker.innerHTML = "";
        areas.forEach(function (a, i) {
          var opt = document.createElement("option");
          opt.value = a.id;
          opt.textContent = a.name || a.code || a.id.slice(0, 10);
          picker.appendChild(opt);
        });
        if (areas.length) {
          currentArea = areas[0].id;
          picker.value = currentArea;
        }
        AdminShell.upgradeSelect("areaPicker");
        populateSendAreaPicker(areas);
      } catch (e) {
        var picker = AdminShell.byId("areaPicker");
        picker.innerHTML = '<option value="">加载域失败</option>';
      }
    }

    function onAreaChange() {
      var picker = AdminShell.byId("areaPicker");
      currentArea = picker.value;
      currentOffset = 0;
      loadMembers();
      loadBlocks();
    }

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setMicroStatus(text, variant, "membersState");
    }

    var esc = AdminShell.escapeHtml;

    /* ========= 自定义弹窗 ========= */

    function openModal(title, bodyHtml, footerHtml) {
      AdminShell.byId("modalTitle").textContent = title;
      AdminShell.byId("modalBody").innerHTML = bodyHtml;
      AdminShell.byId("modalFooter").innerHTML = footerHtml || "";
      AdminShell.byId("modalOverlay").classList.add("is-open");
      AdminShell.byId("modalDialog").classList.add("is-open");
    }

    function closeModal() {
      var dialog = AdminShell.byId("modalDialog");
      var overlay = AdminShell.byId("modalOverlay");
      dialog.classList.remove("is-open");
      overlay.classList.remove("is-open");
      if (_modalResolve) { _modalResolve(null); _modalResolve = null; }
    }

    function pickDuration(type) {
      var label = type === "mic" ? "禁麦" : "禁言";
      var options = [
        { min: 1, val: "1", unit: "分钟" },
        { min: 5, val: "5", unit: "分钟" },
        { min: 60, val: "1", unit: "小时" },
        { min: 1440, val: "1", unit: "天" },
        { min: 4320, val: "3", unit: "天" },
        { min: 10080, val: "7", unit: "天" },
      ];
      var grid = '<div class="m-duration-grid">' + options.map(function (o) {
        return '<button class="m-duration-btn" onclick="_modalResolve(' + o.min + ');closeModal()">' +
          '<span class="m-duration-btn__val">' + o.val + '</span>' +
          '<span class="m-duration-btn__unit">' + o.unit + '</span>' +
          '</button>';
      }).join("") + '</div>';

      return new Promise(function (resolve) {
        _modalResolve = resolve;
        openModal(label + "时长", grid, '<button class="btn btn-ghost" onclick="closeModal()">取消</button>');
      });
    }

    function confirmAction(title, message) {
      return new Promise(function (resolve) {
        _modalResolve = function () { resolve(false); };
        var body = '<div class="m-confirm-text">' + message + '</div>';
        var foot =
          '<button class="btn btn-ghost" onclick="closeModal()">取消</button>' +
          '<button class="btn btn-danger" onclick="_modalResolve=null;closeModal();(' + resolve.name + ' || arguments.callee).__cb(true)">确认</button>';
        openModal(title, body, '');
        AdminShell.byId("modalFooter").innerHTML = "";
        var cancelBtn = document.createElement("button");
        cancelBtn.className = "btn btn-ghost";
        cancelBtn.textContent = "取消";
        cancelBtn.onclick = function () { closeModal(); resolve(false); };
        var okBtn = document.createElement("button");
        okBtn.className = "btn btn-danger";
        okBtn.textContent = "确认";
        okBtn.onclick = function () { _modalResolve = null; closeModal(); resolve(true); };
        AdminShell.byId("modalFooter").appendChild(cancelBtn);
        AdminShell.byId("modalFooter").appendChild(okBtn);
      });
    }

    /* ========= 成员列表 ========= */

    async function loadMembers() {
      var keyword = (AdminShell.byId("memberSearch") || {}).value || "";
      var url = "/admin/api/members?offset=" + currentOffset + "&limit=" + pageSize + "&area=" + encodeURIComponent(getArea());
      if (keyword) url += "&keyword=" + encodeURIComponent(keyword);
      try {
        var data = await AdminShell.req(url);
        totalMembers = data.total || 0;
        AdminShell.animateNumber("totalMembers", totalMembers);
        AdminShell.animateNumber("onlineMembers", data.online || 0);

        var members = data.members || [];
        var rows = members.map(function (m) {
          var isOnline = m.online;
          var dotColor = isOnline ? "#22c55e" : "#cbd5e1";
          var statusLabel = isOnline
            ? '<span class="m-badge m-badge--online">在线</span>'
            : '<span class="m-badge m-badge--offline">离线</span>';
          var activityHtml = "";
          if (m.playingState) {
            var icon = m.displayType === "MUSIC" ? "&#9835; " : "";
            activityHtml = '<div style="font-size:11px;color:var(--ink-faint);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px">' + icon + esc(m.playingState) + '</div>';
          }
          var avatarHtml = m.avatar
            ? '<img src="' + esc(m.avatar) + '" style="width:32px;height:32px;border-radius:50%;object-fit:cover;flex-shrink:0" loading="lazy" onerror="this.style.display=\'none\'">'
            : '<div style="width:32px;height:32px;border-radius:50%;background:var(--bg-soft);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;color:var(--ink-faint)">?</div>';
          var roleHtml = m.roleName
            ? '<span class="m-role-badge">' + esc(m.roleName) + '</span>'
            : '<span style="color:var(--ink-faint);font-size:11px">-</span>';
          return (
            "<tr>" +
              '<td>' +
                '<div style="display:flex;align-items:center;gap:10px">' +
                  '<div style="position:relative;flex-shrink:0">' + avatarHtml +
                    '<span style="position:absolute;bottom:0;right:0;width:10px;height:10px;border-radius:50%;background:' + dotColor + ';border:2px solid var(--paper)"></span>' +
                  '</div>' +
                  '<div style="min-width:0">' +
                    '<div class="table-emphasis" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(m.name) + '</div>' +
                    activityHtml +
                  '</div>' +
                '</div>' +
              '</td>' +
              '<td>' + roleHtml + '</td>' +
              '<td>' + statusLabel + '</td>' +
              '<td><div class="m-member-actions">' +
                '<button class="btn btn-ghost" onclick="showDetail(\'' + esc(m.uid) + '\')">详情</button>' +
                '<button class="btn btn-ghost" onclick="doMute(\'' + esc(m.uid) + '\')">禁言</button>' +
                '<button class="btn btn-danger btn-sm" onclick="doKick(\'' + esc(m.uid) + '\')">踢出</button>' +
              '</div></td>' +
            "</tr>"
          );
        }).join("");

        AdminShell.byId("memberRows").innerHTML =
          rows || '<tr><td colspan="4" class="empty-state">暂无数据</td></tr>';

        var page = Math.floor(currentOffset / pageSize) + 1;
        var pages = Math.max(1, Math.ceil(totalMembers / pageSize));
        AdminShell.byId("pageInfo").textContent = page + " / " + pages;

        if (data.stale) {
          setPageState("已加载 " + members.length + " 条 (缓存数据)", "warning");
        } else {
          setPageState("已同步 " + members.length + " 条", "success");
        }
      } catch (e) {
        setPageState("加载失败: " + e.message, "error");
      }
    }

    function prevPage() {
      if (currentOffset >= pageSize) { currentOffset -= pageSize; loadMembers(); }
    }
    function nextPage() {
      if (currentOffset + pageSize < totalMembers) { currentOffset += pageSize; loadMembers(); }
    }

    /* ========= 用户详情 ========= */

    function _openDrawerImmediate(uid) {
      var overlay = AdminShell.byId("drawerOverlay");
      var drawer = AdminShell.byId("detailDrawer");
      var alreadyOpen = drawer.classList.contains("is-open");
      AdminShell.byId("detailName").textContent = "加载中...";
      var skeletonHtml =
        '<div class="m-profile__skeleton">' +
          '<div class="m-skel m-skel--circle"></div>' +
          '<div class="m-skel m-skel--line" style="width:100px;margin-top:10px"></div>' +
          '<div class="m-skel m-skel--line" style="width:60px;margin-top:6px"></div>' +
        '</div>';
      var infoSkel =
        '<div class="m-skel m-skel--block"></div>' +
        '<div class="m-skel m-skel--block"></div>';
      if (alreadyOpen) {
        var body = drawer.querySelector(".m-drawer__body");
        body.style.transition = "opacity .15s ease";
        body.style.opacity = "0";
        setTimeout(function () {
          AdminShell.byId("detailProfile").innerHTML = skeletonHtml;
          AdminShell.byId("detailInfo").innerHTML = infoSkel;
          AdminShell.byId("detailActions").innerHTML = '';
          AdminShell.byId("detailRoles").innerHTML = '';
          body.style.opacity = "1";
        }, 150);
      } else {
        AdminShell.byId("detailProfile").innerHTML = skeletonHtml;
        AdminShell.byId("detailInfo").innerHTML = infoSkel;
        AdminShell.byId("detailActions").innerHTML = '';
        AdminShell.byId("detailRoles").innerHTML = '';
        overlay.classList.add("is-open");
        drawer.classList.add("is-open");
      }
    }

    function _fillDrawer(uid, data) {
      var p = data.person || {};
      var pName = p.name || uid.slice(0, 12);
      AdminShell.byId("detailName").textContent = pName;

        // profile
        var profileHtml = '';
        if (p.avatar) {
          profileHtml += '<img class="m-profile__avatar" src="' + esc(p.avatar) + '" onerror="this.style.display=\'none\'" loading="lazy">';
        }
        profileHtml += '<div class="m-profile__name">' + esc(pName) + '</div>';
        if (p.pid) profileHtml += '<div class="m-profile__sub">PID ' + esc(p.pid) + '</div>';
        var onlineBadge = p.online
          ? '<span class="m-badge m-badge--online" style="margin-top:8px">在线</span>'
          : '<span class="m-badge m-badge--offline" style="margin-top:8px">离线</span>';
        profileHtml += onlineBadge;
        AdminShell.byId("detailProfile").innerHTML = profileHtml;

        // info grid
        var info = '';
        info += '<div class="m-info-item full"><div class="m-info-label">UID</div><div class="m-info-value" style="font-size:11px">' + esc(uid) + '</div></div>';
        if (p.introduction) {
          info += '<div class="m-info-item full"><div class="m-info-label">简介</div><div class="m-info-value">' + esc(p.introduction) + '</div></div>';
        }

        var muteStatus = data.muted
          ? '<span class="m-badge m-badge--muted">禁言中</span>'
          : '<span style="color:var(--ink-faint);font-size:12px">正常</span>';
        if (data.muted && data.muted_until) {
          muteStatus += '<div style="font-size:11px;color:var(--ink-faint);margin-top:2px">至 ' + new Date(data.muted_until).toLocaleString() + '</div>';
        }
        info += '<div class="m-info-item"><div class="m-info-label">禁言状态</div><div class="m-info-value">' + muteStatus + '</div></div>';

        var micStatus = data.mic_muted
          ? '<span class="m-badge m-badge--muted">禁麦中</span>'
          : '<span style="color:var(--ink-faint);font-size:12px">正常</span>';
        if (data.mic_muted && data.mic_muted_until) {
          micStatus += '<div style="font-size:11px;color:var(--ink-faint);margin-top:2px">至 ' + new Date(data.mic_muted_until).toLocaleString() + '</div>';
        }
        info += '<div class="m-info-item"><div class="m-info-label">禁麦状态</div><div class="m-info-value">' + micStatus + '</div></div>';

        info += '<div class="m-info-item"><div class="m-info-label">近7天消息</div><div class="m-info-value" style="font-size:18px;font-weight:700">' + (data.messages_7d || 0) + '</div></div>';

        var roles = data.roles || [];
        if (roles.length) {
          var rolesHtml = roles.map(function (r) {
            return '<span class="m-role-badge">' + esc(r.name || r.roleID) + '</span>';
          }).join(" ");
          info += '<div class="m-info-item"><div class="m-info-label">当前身份组</div><div class="m-info-value" style="display:flex;flex-wrap:wrap;gap:4px">' + rolesHtml + '</div></div>';
        }
        AdminShell.byId("detailInfo").innerHTML = info;

        // action buttons
        var actions = '';
        if (data.muted) {
          actions += '<button class="btn btn-ghost" onclick="doUnmute(\'' + esc(uid) + '\')">解除禁言</button>';
        } else {
          actions += '<button class="btn btn-ghost" onclick="doMute(\'' + esc(uid) + '\')">禁言</button>';
        }
        if (data.mic_muted) {
          actions += '<button class="btn btn-ghost" onclick="doUnmuteMic(\'' + esc(uid) + '\')">解除禁麦</button>';
        } else {
          actions += '<button class="btn btn-ghost" onclick="doMuteMic(\'' + esc(uid) + '\')">禁麦</button>';
        }
        actions += '<button class="btn btn-danger" onclick="doKick(\'' + esc(uid) + '\')">踢出</button>';
        actions += '<button class="btn btn-danger" onclick="doBlock(\'' + esc(uid) + '\')">封禁</button>';
        AdminShell.byId("detailActions").innerHTML = actions;

        // assignable roles
        var assignable = data.assignable_roles || [];
        var roleSection = '';
        if (assignable.length) {
          roleSection = '<div class="m-role-section__title">身份组管理</div>';
          assignable.forEach(function (r) {
            var rid = r.roleID || r.id || "";
            var rname = esc(r.name || rid);
            var hasRole = roles.some(function (ur) { return (ur.roleID || ur.id) == rid; });
            if (hasRole) {
              roleSection += '<span class="m-role-tag m-role-tag--owned" onclick="doRoleRemove(\'' + esc(uid) + '\',' + rid + ')" title="点击移除">' +
                rname + ' <span class="m-role-tag__icon">&times;</span></span>';
            } else {
              roleSection += '<span class="m-role-tag" onclick="doRoleAdd(\'' + esc(uid) + '\',' + rid + ')" title="点击添加">' +
                rname + ' <span class="m-role-tag__icon">+</span></span>';
            }
          });
        }
        AdminShell.byId("detailRoles").innerHTML = roleSection;

        var body = AdminShell.byId("detailDrawer").querySelector(".m-drawer__body");
        if (body) {
          body.style.opacity = "0";
          body.style.transform = "translateY(6px)";
          requestAnimationFrame(function () {
            body.style.transition = "opacity .25s ease, transform .25s ease";
            body.style.opacity = "1";
            body.style.transform = "translateY(0)";
          });
        }
    }

    async function showDetail(uid) {
      _openDrawerImmediate(uid);
      try {
        var data = await AdminShell.req("/admin/api/members/" + uid + "?area=" + encodeURIComponent(getArea()));
        _fillDrawer(uid, data);
      } catch (e) {
        AdminShell.byId("detailProfile").innerHTML =
          '<div style="text-align:center;padding:24px;color:var(--danger)">加载失败: ' + esc(e.message) + '</div>';
        AdminShell.byId("detailInfo").innerHTML = '';
      }
    }

    function closeDrawer() {
      var overlay = AdminShell.byId("drawerOverlay");
      var drawer = AdminShell.byId("detailDrawer");
      drawer.classList.remove("is-open");
      overlay.classList.remove("is-open");
    }

    /* ========= 管理操作 ========= */

    async function doMute(uid) {
      var dur = await pickDuration("text");
      if (!dur) return;
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/mute", {
          method: "POST", body: JSON.stringify({ duration: dur, area: getArea() }),
        });
        setPageState("已禁言", "success");
        showDetail(uid);
        loadMembers();
      } catch (e) { setPageState("禁言失败: " + e.message, "error"); }
    }

    async function doUnmute(uid) {
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/unmute", { method: "POST", body: JSON.stringify({ area: getArea() }) });
        setPageState("已解除禁言", "success");
        showDetail(uid);
        loadMembers();
      } catch (e) { setPageState("解除禁言失败: " + e.message, "error"); }
    }

    async function doMuteMic(uid) {
      var dur = await pickDuration("mic");
      if (!dur) return;
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/mute-mic", {
          method: "POST", body: JSON.stringify({ duration: dur, area: getArea() }),
        });
        setPageState("已禁麦", "success");
        showDetail(uid);
        loadMembers();
      } catch (e) { setPageState("禁麦失败: " + e.message, "error"); }
    }

    async function doUnmuteMic(uid) {
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/unmute-mic", { method: "POST", body: JSON.stringify({ area: getArea() }) });
        setPageState("已解除禁麦", "success");
        showDetail(uid);
        loadMembers();
      } catch (e) { setPageState("解除禁麦失败: " + e.message, "error"); }
    }

    async function doKick(uid) {
      var ok = await confirmAction("踢出用户", "确认将该用户<strong>踢出域</strong>？此操作不可撤销。");
      if (!ok) return;
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/kick", { method: "POST", body: JSON.stringify({ area: getArea() }) });
        setPageState("已踢出", "success");
        closeDrawer();
        loadMembers();
      } catch (e) { setPageState("踢出失败: " + e.message, "error"); }
    }

    async function doBlock(uid) {
      var ok = await confirmAction("封禁用户", "确认<strong>封禁</strong>该用户？封禁后将被踢出域且无法再加入。");
      if (!ok) return;
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/block", { method: "POST", body: JSON.stringify({ area: getArea() }) });
        setPageState("已封禁", "success");
        closeDrawer();
        loadMembers();
      } catch (e) { setPageState("封禁失败: " + e.message, "error"); }
    }

    async function doUnblock(uid) {
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/unblock", { method: "POST", body: JSON.stringify({ area: getArea() }) });
        setPageState("已解封", "success");
        loadBlocks();
      } catch (e) { setPageState("解封失败: " + e.message, "error"); }
    }

    async function doRoleAdd(uid, roleId) {
      try {
        var data = await AdminShell.req("/admin/api/members/" + uid + "/role", {
          method: "POST", body: JSON.stringify({ role_id: roleId, action: "add", area: getArea() }),
        });
        setPageState(data.message || "角色已添加", "success");
        showDetail(uid);
        loadMembers();
      } catch (e) { setPageState("添加角色失败: " + e.message, "error"); }
    }

    async function doRoleRemove(uid, roleId) {
      try {
        var data = await AdminShell.req("/admin/api/members/" + uid + "/role", {
          method: "POST", body: JSON.stringify({ role_id: roleId, action: "remove", area: getArea() }),
        });
        setPageState(data.message || "角色已移除", "success");
        showDetail(uid);
        loadMembers();
      } catch (e) { setPageState("移除角色失败: " + e.message, "error"); }
    }

    /* ========= 封禁列表 ========= */

    async function loadBlocks() {
      try {
        var data = await AdminShell.req("/admin/api/members/blocks?area=" + encodeURIComponent(getArea()));
        var blocks = data.blocks || [];
        AdminShell.animateNumber("blockedCount", blocks.length);
        var card = AdminShell.byId("blocksCard");
        card.style.display = "block";
        var rows = blocks.map(function (b) {
          return (
            "<tr>" +
              '<td class="table-emphasis">' + esc(b.name) + "</td>" +
              "<td style=\"font-size:12px;color:var(--ink-faint)\">" + esc((b.uid || "").slice(0, 12)) + "...</td>" +
              "<td>" +
                '<button class="btn btn-ghost btn-sm" onclick="doUnblock(\'' + esc(b.uid) + '\')">解封</button>' +
              "</td>" +
            "</tr>"
          );
        }).join("");
        AdminShell.byId("blockRows").innerHTML =
          rows || '<tr><td colspan="3" class="empty-state">暂无封禁</td></tr>';
      } catch (e) {
        AdminShell.animateNumber("blockedCount", 0);
        var card = AdminShell.byId("blocksCard");
        card.style.display = "block";
        AdminShell.byId("blockRows").innerHTML =
          '<tr><td colspan="3" class="empty-state">加载失败: ' + esc(e.message) + '</td></tr>';
      }
    }

    /* ========= 发送消息/公告 ========= */

    var sendArea = "";

    function getSendArea() { return sendArea || getArea(); }

    function populateSendAreaPicker(areas) {
      var picker = AdminShell.byId("sendAreaPicker");
      if (!picker) return;
      picker.innerHTML = "";
      (areas || []).forEach(function (a) {
        var opt = document.createElement("option");
        opt.value = a.id;
        opt.textContent = a.name || a.code || a.id.slice(0, 10);
        picker.appendChild(opt);
      });
      if (areas && areas.length) {
        sendArea = areas[0].id;
        picker.value = sendArea;
      }
      AdminShell.upgradeSelect("sendAreaPicker");
    }

    function onSendAreaChange() {
      var picker = AdminShell.byId("sendAreaPicker");
      sendArea = picker.value;
      refreshChannels();
    }

    async function refreshChannels() {
      var picker = AdminShell.byId("channelPicker");
      picker.innerHTML = '<option value="">加载中...</option>';
      try {
        var data = await AdminShell.req("/admin/api/channels?area=" + encodeURIComponent(getSendArea()));
        var channels = data.channels || [];
        picker.innerHTML = '<option value="">选择频道...</option>';
        var lastGroup = "";
        var optgroup = null;
        channels.forEach(function (ch) {
          if (ch.group && ch.group !== lastGroup) {
            lastGroup = ch.group;
            optgroup = document.createElement("optgroup");
            optgroup.label = ch.group;
            picker.appendChild(optgroup);
          }
          var opt = document.createElement("option");
          opt.value = ch.id;
          var typeLabel = ch.type === "VOICE" ? " [语音]" : "";
          opt.textContent = (ch.name || ch.id) + typeLabel;
          (optgroup || picker).appendChild(opt);
        });
      } catch (e) {
        picker.innerHTML = '<option value="">加载频道失败</option>';
      }
      AdminShell.upgradeSelect("channelPicker");
    }

    function _setSendStatus(text, isErr) {
      var el = AdminShell.byId("sendStatus");
      el.textContent = text;
      el.className = "m-send-status " + (isErr ? "is-err" : "is-ok");
      el.style.opacity = "1";
      if (text) {
        clearTimeout(el._timer);
        el._timer = setTimeout(function () { el.style.opacity = "0"; }, 4000);
      }
    }

    async function doSendMessage() {
      var channel = (AdminShell.byId("channelPicker") || {}).value || "";
      var text = (AdminShell.byId("sendContent") || {}).value || "";
      if (!channel) { _setSendStatus("请先选择频道", true); return; }
      if (!text.trim()) { _setSendStatus("消息内容不能为空", true); return; }
      try {
        _setSendStatus("发送中...", false);
        await AdminShell.req("/admin/api/send-message", {
          method: "POST",
          body: JSON.stringify({ area: getSendArea(), channel: channel, text: text }),
        });
        _setSendStatus("消息已发送", false);
        AdminShell.byId("sendContent").value = "";
      } catch (e) {
        _setSendStatus("发送失败: " + e.message, true);
      }
    }

    async function doSendAnnouncement() {
      var channel = (AdminShell.byId("channelPicker") || {}).value || "";
      var text = (AdminShell.byId("sendContent") || {}).value || "";
      if (!channel) { _setSendStatus("请先选择频道", true); return; }
      if (!text.trim()) { _setSendStatus("公告内容不能为空", true); return; }
      try {
        _setSendStatus("发送中...", false);
        await AdminShell.req("/admin/api/send-announcement", {
          method: "POST",
          body: JSON.stringify({ area: getSendArea(), channel: channel, text: text }),
        });
        _setSendStatus("公告已发送", false);
        AdminShell.byId("sendContent").value = "";
      } catch (e) {
        _setSendStatus("发送失败: " + e.message, true);
      }
    }

    /* ========= 初始化 ========= */

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录成员管理",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadAreas();
        await loadMembers();
        loadBlocks();
        refreshChannels();
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

    AdminShell.init({ page: "members", passwordHandler: login });
    check();
