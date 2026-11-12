    var currentOffset = 0;
    var pageSize = 50;
    var totalMembers = 0;
    var currentArea = "";

    var MUTE_PRESETS = [
      { min: 1, val: "1", unit: "分钟" },
      { min: 5, val: "5", unit: "分钟" },
      { min: 60, val: "1", unit: "小时" },
      { min: 1440, val: "1", unit: "天" },
      { min: 4320, val: "3", unit: "天" },
      { min: 10080, val: "7", unit: "天" },
    ];

    // uid -> 该成员所属域。跨域列表下每个成员可能来自不同域，
    // 管理操作必须作用到成员自己的域，不能用 "__all__"。
    var memberAreaMap = {};

    // 列表 / 查询用：原样返回当前选择，可能是 "__all__"（跨域聚合）。
    function getArea() {
      return currentArea;
    }

    // 管理操作用：必须落到某个真实域。跨域列表里成员可能同时属于多个域，
    // 这时静默挑一个会禁错/踢错域，所以交给使用者确认。
    async function getMemberArea(uid) {
      if (currentArea !== "__all__") return currentArea;
      var areas = (uid && memberAreaMap[uid]) || [];
      if (!areas.length) return "";
      if (areas.length === 1) return areas[0].areaId;
      return await AdminShell.pickArea(areas);
    }

    // 只读展示用：取权限最高的域，不打断操作者
    function getMemberAreaPrimary(uid) {
      if (currentArea !== "__all__") return currentArea;
      var areas = (uid && memberAreaMap[uid]) || [];
      return areas.length ? areas[0].areaId : "";
    }

    async function loadAreas() {
      try {
        var data = await AdminShell.req("/admin/api/areas");
        // 按用户在标签条上拖出来的顺序排列，排第一的即默认加载的域
        var areas = AdminShell.applyAreaOrder(data.areas || []);
        var picker = AdminShell.byId("areaPicker");
        picker.innerHTML = "";
        // 「全部域」放在最前：跨域搜人不用再一个个域点过去
        if (areas.length > 1) {
          var allOpt = document.createElement("option");
          allOpt.value = "__all__";
          allOpt.textContent = "全部域";
          picker.appendChild(allOpt);
        }
        areas.forEach(function (a) {
          var opt = document.createElement("option");
          opt.value = a.id;
          opt.textContent = a.name || a.code || a.id.slice(0, 10);
          picker.appendChild(opt);
        });
        if (areas.length) {
          // 默认选排在最前的那个域（顺序由标签条拖动决定）。不默认「全部域」是
          // 因为跨域聚合要并发拉全部域，首次约 2 秒，不该每次开页面都付这个代价。
          currentArea = areas[0].id;
          picker.value = currentArea;
        }
        AdminShell.renderAreaTabs("areaPicker", "areaTabs");
        populateSendAreaPicker(areas);
      } catch (e) {
        var picker = AdminShell.byId("areaPicker");
        picker.innerHTML = '<option value="">加载域失败</option>';
        AdminShell.renderAreaTabs("areaPicker", "areaTabs");
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

    function pickDuration(type) {
      var label = type === "mic" ? "禁麦" : "禁言";
      return new Promise(function (resolve) {
        var settled = false;
        function done(value) {
          if (settled) return;
          settled = true;
          AdminShell.closeModal();
          resolve(value);
        }
        var grid = document.createElement("div");
        grid.className = "m-duration-grid";
        MUTE_PRESETS.forEach(function (preset) {
          var btn = document.createElement("button");
          btn.className = "m-duration-btn";
          btn.innerHTML =
            '<span class="m-duration-btn__val">' + preset.val + "</span>" +
            '<span class="m-duration-btn__unit">' + preset.unit + "</span>";
          btn.addEventListener("click", function () { done(preset.min); });
          grid.appendChild(btn);
        });

        AdminShell.openModal(label + "时长", "", null, function () {
          if (!settled) { settled = true; resolve(0); }
        });
        var bodyEl = AdminShell.byId("modalBody");
        if (bodyEl) { bodyEl.innerHTML = ""; bodyEl.appendChild(grid); }
        var footEl = AdminShell.byId("modalFooter");
        if (footEl) {
          footEl.innerHTML = "";
          var cancelBtn = document.createElement("button");
          cancelBtn.className = "btn btn-ghost";
          cancelBtn.textContent = "取消";
          cancelBtn.addEventListener("click", function () { done(0); });
          footEl.appendChild(cancelBtn);
        }
      });
    }

    /* ========= 成员列表 ========= */

    async function loadMembers() {
      var keyword = (AdminShell.byId("memberSearch") || {}).value || "";
      // 「全部域」要把各域成员一起铺出来，用单域分页的 50 会被靠前的域占满，
      // 看上去像只显示了一个域。这条路径由后端从内存池切片，放大页长不会更慢。
      var isAll = getArea() === "__all__";
      var size = isAll ? 500 : pageSize;
      var url = "/admin/api/members?offset=" + currentOffset + "&limit=" + size + "&area=" + encodeURIComponent(getArea());
      if (keyword) url += "&keyword=" + encodeURIComponent(keyword);
      try {
        var data = await AdminShell.req(url);
        totalMembers = data.total || 0;
        AdminShell.animateNumber("totalMembers", totalMembers);
        AdminShell.animateNumber("onlineMembers", data.online || 0);

        var members = data.members || [];
        if (data.crossArea) {
          memberAreaMap = {};
          members.forEach(function (m) {
            if (m.uid && m.areas && m.areas.length) memberAreaMap[m.uid] = m.areas;
          });
        }
        var rows = members.map(function (m) {
          var isOnline = m.online;
          var dotColor = isOnline ? "#22c55e" : "#cbd5e1";
          var statusLabel = isOnline
            ? '<span class="m-badge m-badge--online">在线</span>'
            : '<span class="m-badge m-badge--offline">离线</span>';
          // 一个人可能同时在多个域，逐个标注，不能只显示主域
          var areaHtml = (m.areas && m.areas.length)
            ? m.areas.map(function (a) {
                return '<span class="m-area-chip">' + esc(a.areaName) + '</span>';
              }).join("")
            : (m.areaName ? '<span class="m-area-chip">' + esc(m.areaName) + '</span>' : "");
          var activityHtml = "";
          if (m.playingState) {
            var icon = m.displayType === "MUSIC" ? "&#9835; " : "";
            activityHtml = '<div style="font-size:11px;color:var(--ink-faint);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px">' + icon + esc(m.playingState) + '</div>';
          }
          var avatarHtml = m.avatar
            ? '<img src="' + esc(m.avatar) + '" style="width:32px;height:32px;border-radius:50%;object-fit:cover;flex-shrink:0" loading="lazy" onerror="this.style.display=\'none\'">'
            : '<div style="width:32px;height:32px;border-radius:50%;background:var(--bg-soft);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;color:var(--ink-faint)">?</div>';
          var adminTag = m.is_bot_admin
            ? '<span class="m-role-badge m-role-badge--admin">管理员</span> '
            : '';
          var roleHtml = m.roleName
            ? adminTag + '<span class="m-role-badge">' + esc(m.roleName) + '</span>'
            : adminTag || '<span style="color:var(--ink-faint);font-size:11px">-</span>';
          return (
            "<tr>" +
              '<td>' +
                '<div style="display:flex;align-items:center;gap:10px">' +
                  '<div style="position:relative;flex-shrink:0">' + avatarHtml +
                    '<span style="position:absolute;bottom:0;right:0;width:10px;height:10px;border-radius:50%;background:' + dotColor + ';border:2px solid var(--paper)"></span>' +
                  '</div>' +
                  '<div style="min-width:0">' +
                    '<div class="table-emphasis" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(m.name) + areaHtml + '</div>' +
                    activityHtml +
                  '</div>' +
                '</div>' +
              '</td>' +
              '<td>' + roleHtml + '</td>' +
              '<td>' + statusLabel + '</td>' +
              '<td><div class="m-member-actions">' +
                '<button class="btn btn-ghost" type="button" data-action="show-detail" data-uid="' + esc(m.uid) + '">详情</button>' +
                '<button class="btn btn-ghost" type="button" data-action="do-mute" data-uid="' + esc(m.uid) + '">禁言</button>' +
                '<button class="btn btn-danger btn-sm" type="button" data-action="do-kick" data-uid="' + esc(m.uid) + '">踢出</button>' +
              '</div></td>' +
            "</tr>"
          );
        }).join("");

        AdminShell.byId("memberRows").innerHTML =
          rows || '<tr><td colspan="4" class="empty-state">暂无数据</td></tr>';

        // 跨域是一次铺完的，分页按 size 而不是单域的 pageSize 计算，否则会显示成多页
        var step = isAll ? size : pageSize;
        var page = Math.floor(currentOffset / step) + 1;
        var pages = Math.max(1, Math.ceil(totalMembers / step));
        AdminShell.byId("pageInfo").textContent = page + " / " + pages;

        if (data.partial && data.partial.length) {
          setPageState("已加载 " + members.length + " 条，这些域取数失败: " + data.partial.join("、"), "warning");
        } else if (data.stale) {
          setPageState("已加载 " + members.length + " 条 (缓存数据)", "warning");
        } else if (isAll) {
          setPageState("已同步 " + members.length + " 条（全部 " + totalMembers + " 人）", "success");
        } else {
          setPageState("已同步 " + members.length + " 条", "success");
        }
      } catch (e) {
        setPageState("加载失败: " + e.message, "error");
      }
    }

    function _step() { return getArea() === "__all__" ? 500 : pageSize; }
    function prevPage() {
      var step = _step();
      if (currentOffset >= step) { currentOffset -= step; loadMembers(); }
    }
    function nextPage() {
      var step = _step();
      if (currentOffset + step < totalMembers) { currentOffset += step; loadMembers(); }
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

        // admin badge
        var adminBadge = '';
        if (data.is_bot_admin) {
          adminBadge = '<span class="m-badge m-badge--admin" style="margin-top:6px">Bot 管理员</span>';
        }
        var profileEl = AdminShell.byId("detailProfile");
        profileEl.innerHTML += adminBadge;

        // action buttons
        var actions = '';
        if (data.is_bot_admin) {
          actions += '<button class="btn btn-ghost m-btn--admin-revoke" type="button" data-action="remove-admin" data-uid="' + esc(uid) + '">撤销管理员</button>';
        } else {
          actions += '<button class="btn btn-ghost m-btn--admin-grant" type="button" data-action="grant-admin" data-uid="' + esc(uid) + '">设为管理员</button>';
        }
        if (data.muted) {
          actions += '<button class="btn btn-ghost" type="button" data-action="do-unmute" data-uid="' + esc(uid) + '">解除禁言</button>';
        } else {
          actions += '<button class="btn btn-ghost" type="button" data-action="do-mute" data-uid="' + esc(uid) + '">禁言</button>';
        }
        if (data.mic_muted) {
          actions += '<button class="btn btn-ghost" type="button" data-action="do-unmute-mic" data-uid="' + esc(uid) + '">解除禁麦</button>';
        } else {
          actions += '<button class="btn btn-ghost" type="button" data-action="do-mute-mic" data-uid="' + esc(uid) + '">禁麦</button>';
        }
        actions += '<button class="btn btn-danger" type="button" data-action="do-kick" data-uid="' + esc(uid) + '">踢出</button>';
        actions += '<button class="btn btn-danger" type="button" data-action="do-block" data-uid="' + esc(uid) + '">封禁</button>';
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
              roleSection += '<span class="m-role-tag m-role-tag--owned" data-action="role-remove" data-uid="' + esc(uid) + '" data-rid="' + rid + '" title="点击移除">' +
                rname + ' <span class="m-role-tag__icon">&times;</span></span>';
            } else {
              roleSection += '<span class="m-role-tag" data-action="role-add" data-uid="' + esc(uid) + '" data-rid="' + rid + '" title="点击添加">' +
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

    async function showDetail(uid, area) {
      _openDrawerImmediate(uid);
      try {
        var data = await AdminShell.req("/admin/api/members/" + uid + "?area=" + encodeURIComponent(area || getMemberAreaPrimary(uid)));
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

    async function moderate(uid, action, label, extra, closeAfter) {
      var area = await getMemberArea(uid);
      if (!area) return;
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/" + action, {
          method: "POST", body: JSON.stringify(Object.assign({ area: area }, extra)),
        });
        setPageState("已" + label, "success");
        if (closeAfter) closeDrawer(); else showDetail(uid, area);
        loadMembers();
      } catch (e) { setPageState(label + "失败: " + e.message, "error"); }
    }

    async function doMute(uid) {
      var dur = await pickDuration("text");
      if (dur) await moderate(uid, "mute", "禁言", { duration: dur });
    }

    async function doUnmute(uid) { await moderate(uid, "unmute", "解除禁言"); }

    async function doMuteMic(uid) {
      var dur = await pickDuration("mic");
      if (dur) await moderate(uid, "mute-mic", "禁麦", { duration: dur });
    }

    async function doUnmuteMic(uid) { await moderate(uid, "unmute-mic", "解除禁麦"); }

    async function doKick(uid) {
      if (await AdminShell.confirm("踢出用户", "确认将该用户<strong>踢出域</strong>？此操作不可撤销。")) {
        await moderate(uid, "kick", "踢出", null, true);
      }
    }

    async function doBlock(uid) {
      if (await AdminShell.confirm("封禁用户", "确认<strong>封禁</strong>该用户？封禁后将被踢出域且无法再加入。")) {
        await moderate(uid, "block", "封禁", null, true);
      }
    }

    // 被封禁的人已不在成员列表里，查不到 memberAreaMap，域由列表行直接带过来
    async function doUnblock(uid, area) {
      area = area || getMemberAreaPrimary(uid);
      if (!area) {
        setPageState("解封失败: 无法确定该封禁所属的域", "error");
        return;
      }
      try {
        await AdminShell.req("/admin/api/members/" + uid + "/unblock", { method: "POST", body: JSON.stringify({ area: area }) });
        setPageState("已解封", "success");
        loadBlocks();
      } catch (e) { setPageState("解封失败: " + e.message, "error"); }
    }

    async function doRoleAdd(uid, roleId) {
      var area = await getMemberArea(uid);
      if (!area) return;
      try {
        var data = await AdminShell.req("/admin/api/members/" + uid + "/role", {
          method: "POST", body: JSON.stringify({ role_id: roleId, action: "add", area: area }),
        });
        setPageState(data.message || "角色已添加", "success");
        showDetail(uid, area);
        loadMembers();
      } catch (e) { setPageState("添加角色失败: " + e.message, "error"); }
    }

    async function doRoleRemove(uid, roleId) {
      var area = await getMemberArea(uid);
      if (!area) return;
      try {
        var data = await AdminShell.req("/admin/api/members/" + uid + "/role", {
          method: "POST", body: JSON.stringify({ role_id: roleId, action: "remove", area: area }),
        });
        setPageState(data.message || "角色已移除", "success");
        showDetail(uid, area);
        loadMembers();
      } catch (e) { setPageState("移除角色失败: " + e.message, "error"); }
    }

    /* ========= Bot 管理员操作 ========= */

    async function doGrantAdmin(uid) {
      var ok = await AdminShell.confirm("设为管理员", "确认将该用户设为 <strong>Bot 管理员</strong>？管理员可执行所有管理命令。");
      if (!ok) return;
      try {
        await AdminShell.req("/admin/api/bot-admins", {
          method: "POST", body: JSON.stringify({ uid: uid }),
        });
        setPageState("已设为管理员", "success");
        showDetail(uid, area);
        loadMembers();
      } catch (e) { setPageState("设置管理员失败: " + e.message, "error"); }
    }

    async function doRemoveAdmin(uid) {
      var ok = await AdminShell.confirm("撤销管理员", "确认<strong>撤销</strong>该用户的 Bot 管理员权限？");
      if (!ok) return;
      try {
        await AdminShell.req("/admin/api/bot-admins/" + uid, { method: "DELETE" });
        setPageState("已撤销管理员", "success");
        showDetail(uid, area);
        loadMembers();
      } catch (e) { setPageState("撤销管理员失败: " + e.message, "error"); }
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
          // 封禁按域生效，解封必须回到封禁所在的域，所以把域随按钮一起带上
          var chip = (data.crossArea && b.areaName)
            ? ' <span class="m-area-chip">' + esc(b.areaName) + "</span>"
            : "";
          return (
            "<tr>" +
              '<td class="table-emphasis">' + esc(b.name) + chip + "</td>" +
              "<td style=\"font-size:12px;color:var(--ink-faint)\">" + esc((b.uid || "").slice(0, 12)) + "...</td>" +
              "<td>" +
                '<button class="btn btn-ghost btn-sm" type="button" data-action="do-unblock"' +
                  ' data-uid="' + esc(b.uid) + '" data-area="' + esc(b.areaId || "") + '">解封</button>' +
              "</td>" +
            "</tr>"
          );
        }).join("");
        var partial = data.partial || [];
        var warning = partial.length
          ? '<tr><td colspan="3" class="empty-state">结果不完整，以下域查询失败：' +
            partial.map(function (item) { return esc(item.areaName || item.areaId) + "（" + esc(item.error) + "）"; }).join("、") +
            '</td></tr>'
          : "";
        AdminShell.byId("blockRows").innerHTML = warning +
          (rows || '<tr><td colspan="3" class="empty-state">' +
            (partial.length ? "已成功查询的域暂无封禁" : "暂无封禁") + '</td></tr>');
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

    AdminShell.registerActions({
      "refresh-members": () => loadMembers(),
      "load-blocks": () => loadBlocks(),
      "members-prev": () => prevPage(),
      "members-next": () => nextPage(),
      "refresh-channels": () => refreshChannels(),
      "send-message": () => doSendMessage(),
      "send-announcement": () => doSendAnnouncement(),
      "close-drawer": () => closeDrawer(),
      "show-detail": (el) => showDetail(el.dataset.uid),
      "do-mute": (el) => doMute(el.dataset.uid),
      "do-unmute": (el) => doUnmute(el.dataset.uid),
      "do-mute-mic": (el) => doMuteMic(el.dataset.uid),
      "do-unmute-mic": (el) => doUnmuteMic(el.dataset.uid),
      "do-kick": (el) => doKick(el.dataset.uid),
      "do-block": (el) => doBlock(el.dataset.uid),
      "do-unblock": (el) => doUnblock(el.dataset.uid, el.dataset.area),
      "grant-admin": (el) => doGrantAdmin(el.dataset.uid),
      "remove-admin": (el) => doRemoveAdmin(el.dataset.uid),
      "role-add": (el) => doRoleAdd(el.dataset.uid, Number(el.dataset.rid)),
      "role-remove": (el) => doRoleRemove(el.dataset.uid, Number(el.dataset.rid)),
      "area-change": () => onAreaChange(),
      "send-area-change": () => onSendAreaChange(),
    });
    AdminShell.bootstrapAuth({
      page: "members",
      loggedInText: "已登录成员管理",
      loginSuccessMessage: null,
      onLogin: async () => {
        await loadAreas();
        await loadMembers();
        loadBlocks();
        refreshChannels();
      },
      onLoggedOut: () => setPageState("等待同步", "warning"),
      onLoginError: () => setPageState("登录失败", "error"),
    });
