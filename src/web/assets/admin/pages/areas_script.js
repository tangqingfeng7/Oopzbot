    let currentArea = "";
    let channelsData = [];
    let areaRolesData = [];
    let voiceChannelsData = [];
    let pendingAreaInvites = [];

    function setState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setStatus(text, variant, "areaState");
    }

    async function loadAreaManager() {
      await Promise.all([loadAreas(), loadAreaInvites()]);
      if (currentArea) {
        await Promise.all([loadAreaRoles(), loadChannels(), loadVoiceChannels()]);
        await loadAreaConfig();
      } else {
        resetAreaAssistantFields();
      }
      setState("已同步", "success");
    }

    async function loadAreas() {
      const picker = AdminShell.byId("areaPicker");
      try {
        const data = await AdminShell.req("/admin/api/areas");
        // 与成员页共用同一份拖动顺序，排第一的即默认加载的域
        const areas = AdminShell.applyAreaOrder(data.areas || []);
        picker.innerHTML = areas.length
          ? areas.map((a) => `<option value="${a.id}">${a.name || a.id}</option>`).join("")
          : '<option value="">无可用域</option>';
        const currentStillJoined = areas.some((area) => area.id === currentArea);
        if (!currentStillJoined) currentArea = areas.length ? areas[0].id : "";
        if (currentArea) {
          picker.value = currentArea;
        }
      } catch (e) {
        currentArea = "";
        picker.innerHTML = '<option value="">加载失败</option>';
      }
      AdminShell.byId("leaveAreaBtn").disabled = !currentArea;
      AdminShell.renderAreaTabs("areaPicker", "areaTabs");
    }

    // ---- Area invites ----

    function safeInviteImageUrl(value) {
      const url = String(value || "").trim();
      return /^https?:\/\//i.test(url) ? url : "";
    }

    function renderAreaInvites(invites) {
      pendingAreaInvites = invites || [];
      const list = AdminShell.byId("areaInviteList");
      if (!pendingAreaInvites.length) {
        list.innerHTML = '<div class="empty-state">暂无待处理的私信域邀请</div>';
        return;
      }
      list.innerHTML = pendingAreaInvites.map((invite) => {
        const banner = safeInviteImageUrl(invite.banner);
        const avatar = safeInviteImageUrl(invite.areaAvatar);
        const sender = invite.senderName || invite.senderId || "未知用户";
        const status = invite.reason || (invite.status === "INVITE_NORMAL" ? "邀请有效" : invite.status || "状态未知");
        const acceptText = invite.joined ? "已经加入" : "同意并加入";
        return `<article class="a-invite-item">
          <div class="a-invite-media">
            ${banner ? `<img class="a-invite-banner" src="${esc(banner)}" alt="域横幅" loading="lazy" />` : '<div class="a-invite-banner"></div>'}
            ${avatar ? `<img class="a-invite-avatar" src="${esc(avatar)}" alt="域头像" loading="lazy" />` : ""}
          </div>
          <div class="a-invite-detail">
            <strong>${esc(invite.areaName || "未命名域")}</strong>
            <span>邀请频道：${esc(invite.channelName || invite.channel || "未提供")}</span>
            <span>发送者：${esc(sender)}${invite.senderId ? `（${esc(invite.senderId)}）` : ""}</span>
            <span>收到时间：${esc(invite.receivedAt || "未知")}</span>
            <span>域 ID：<code>${esc(invite.area || "-")}</code></span>
            <span class="micro-status ${invite.canAccept ? "is-success" : "is-warning"}">${esc(status)}</span>
            <div class="a-invite-actions">
              <button class="btn btn-primary btn-sm" type="button" data-action="accept-area-invite"
                data-code="${esc(invite.code)}" ${invite.canAccept ? "" : "disabled"}>${acceptText}</button>
              <button class="btn btn-ghost btn-sm" type="button" data-action="reject-area-invite"
                data-code="${esc(invite.code)}">忽略</button>
            </div>
          </div>
        </article>`;
      }).join("");
    }

    async function loadAreaInvites() {
      try {
        const data = await AdminShell.req("/admin/api/area-invites");
        renderAreaInvites(data.invites || []);
        AdminShell.showMessage("areaInviteMsg", "");
      } catch (e) {
        renderAreaInvites([]);
        AdminShell.showMessage("areaInviteMsg", "加载待处理邀请失败: " + e.message, true);
      }
    }

    async function acceptAreaInvite(code) {
      const invite = pendingAreaInvites.find((item) => item.code === code);
      if (!invite || !invite.canAccept) return;
      const label = invite.areaName || invite.area;
      const confirmed = await AdminShell.confirm(
        "接受域邀请",
        `确认让 Bot 加入「<strong>${esc(label)}</strong>」？`,
        { danger: false, okText: "接受邀请" },
      );
      if (!confirmed) return;

      AdminShell.showMessage("areaInviteMsg", "Bot 正在接受邀请...");
      try {
        const data = await AdminShell.req("/admin/api/area-invites/accept", {
          method: "POST",
          body: JSON.stringify({ code: code }),
        });
        currentArea = data.invite && data.invite.area ? data.invite.area : currentArea;
        await loadAreaManager();
        AdminShell.showMessage("areaInviteMsg", data.message || "Bot 已加入该域");
        setState("已加入新域", "success");
      } catch (e) {
        AdminShell.showMessage("areaInviteMsg", "接受邀请失败: " + e.message, true);
      }
    }

    async function rejectAreaInvite(code) {
      const invite = pendingAreaInvites.find((item) => item.code === code);
      if (!invite) return;
      const label = invite.areaName || invite.area;
      const confirmed = await AdminShell.confirm(
        "忽略域邀请",
        `确认忽略「<strong>${esc(label)}</strong>」的邀请？`,
        { danger: false, okText: "忽略" },
      );
      if (!confirmed) return;
      try {
        await AdminShell.req("/admin/api/area-invites/reject", {
          method: "POST",
          body: JSON.stringify({ code: code }),
        });
        await loadAreaInvites();
        AdminShell.showMessage("areaInviteMsg", "已忽略该域邀请");
      } catch (e) {
        AdminShell.showMessage("areaInviteMsg", "忽略邀请失败: " + e.message, true);
      }
    }

    function onAreaChange() {
      currentArea = AdminShell.byId("areaPicker").value;
      if (currentArea) {
        setSelectLoading("ac_default_channel_select", "正在加载频道...");
        setSelectLoading("ac_auto_role_select", "正在加载身份组...");
        Promise.all([loadAreaRoles(), loadChannels(), loadVoiceChannels()]).then(loadAreaConfig);
      } else {
        resetAreaAssistantFields();
      }
    }

    async function leaveCurrentArea() {
      if (!currentArea) return;
      const picker = AdminShell.byId("areaPicker");
      const option = picker.options[picker.selectedIndex];
      const areaName = option ? option.textContent : currentArea;
      const confirmed = await AdminShell.confirm(
        "退出当前域",
        `确认让 Bot 退出「<strong>${esc(areaName)}</strong>」？退出后将无法继续读取该域消息。`,
        { okText: "确认退出" },
      );
      if (!confirmed) return;

      const leavingArea = currentArea;
      const button = AdminShell.byId("leaveAreaBtn");
      button.disabled = true;
      button.textContent = "正在退出...";
      try {
        const data = await AdminShell.req("/admin/api/areas/leave", {
          method: "POST",
          body: JSON.stringify({ area: leavingArea }),
        });
        currentArea = "";
        await loadAreaManager();
        setState(data.message || "Bot 已退出该域", "success");
      } catch (e) {
        button.disabled = false;
        setState("退出域失败: " + e.message, "error");
      } finally {
        button.textContent = "退出当前域";
      }
    }

    // ---- Area config ----

    function setAcVal(id, value) {
      const el = AdminShell.byId(id);
      if (!el) return;
      if (el.type === "checkbox") el.checked = !!value;
      else el.value = value ?? "";
    }

    function getAcVal(id) {
      const el = AdminShell.byId(id);
      return el ? (el.value || "") : "";
    }

    function setSelectLoading(id, text) {
      const el = AdminShell.byId(id);
      if (!el) return;
      el.innerHTML = `<option value="">${esc(text || "加载中...")}</option>`;
      AdminShell.refreshCustomSelect(id);
    }

    function resetAreaAssistantFields() {
      channelsData = [];
      areaRolesData = [];
      setSelectLoading("ac_default_channel_select", "先选择域后加载频道");
      setSelectLoading("ac_auto_role_select", "先选择域后加载身份组");
    }

    function populateChannelSelect(selectedValue) {
      const el = AdminShell.byId("ac_default_channel_select");
      if (!el) return;
      const groups = new Map();
      (channelsData || []).forEach((ch) => {
        const groupName = ch.group || "未分组";
        if (!groups.has(groupName)) {
          groups.set(groupName, []);
        }
        groups.get(groupName).push(ch);
      });

      let html = '<option value="">不设置</option>';
      let matched = !selectedValue;
      groups.forEach((items, groupName) => {
        html += `<optgroup label="${esc(groupName)}">`;
        items.forEach((ch) => {
          const value = String(ch.id || "");
          const label = ch.name ? `${ch.name} (${value})` : value;
          if (value === selectedValue) matched = true;
          html += `<option value="${esc(value)}">${esc(label)}</option>`;
        });
        html += "</optgroup>";
      });

      if (selectedValue && !matched) {
        html += `<option value="${esc(selectedValue)}">当前已保存值 (${esc(selectedValue)})</option>`;
      }
      if (!channelsData.length) {
        html = selectedValue
          ? `<option value="${esc(selectedValue)}">当前已保存值 (${esc(selectedValue)})</option>`
          : '<option value="">暂无可选频道</option>';
      }

      el.innerHTML = html;
      el.value = selectedValue || "";
      AdminShell.refreshCustomSelect("ac_default_channel_select");
    }

    function populateRoleSelect(selectedRoleId, selectedRoleName) {
      const el = AdminShell.byId("ac_auto_role_select");
      if (!el) return;
      let html = '<option value="">不自动分配</option>';
      let matched = !selectedRoleId;

      (areaRolesData || []).forEach((role) => {
        const roleId = String(role.id || "");
        const roleName = String(role.name || "");
        const label = roleName ? `${roleName} (${roleId})` : roleId;
        if (roleId === selectedRoleId) matched = true;
        html += `<option value="${esc(roleId)}" data-role-name="${esc(roleName)}">${esc(label)}</option>`;
      });

      if (selectedRoleId && !matched) {
        const fallbackName = selectedRoleName || "当前已保存身份组";
        html += `<option value="${esc(selectedRoleId)}" data-role-name="${esc(fallbackName)}">${esc(fallbackName)} (${esc(selectedRoleId)})</option>`;
      }
      if (!areaRolesData.length) {
        if (selectedRoleId) {
          const fallbackName = selectedRoleName || "当前已保存身份组";
          html = `<option value="${esc(selectedRoleId)}" data-role-name="${esc(fallbackName)}">${esc(fallbackName)} (${esc(selectedRoleId)})</option>`;
        } else {
          html = '<option value="">暂无可选身份组</option>';
        }
      }

      el.innerHTML = html;
      el.value = selectedRoleId || "";
      AdminShell.refreshCustomSelect("ac_auto_role_select");
    }

    function populateScreenShareRoles(selectedIds) {
      const root = AdminShell.byId("ac_screen_share_roles");
      if (!root) return;
      const selected = new Set((selectedIds || []).map((value) => String(value)));
      if (!areaRolesData.length) {
        root.innerHTML = '<span class="a-am-empty">暂无可选身份组</span>';
        return;
      }
      root.innerHTML = areaRolesData.map((role) => {
        const id = String(role.id || "");
        const name = String(role.name || id);
        const checked = selected.has(id) ? " checked" : "";
        return `<label class="a-am-item"><input type="checkbox" value="${esc(id)}"${checked} /> ${esc(name)} <small>(${esc(id)})</small></label>`;
      }).join("");
    }

    function selectedScreenShareRoles() {
      return Array.from(document.querySelectorAll("#ac_screen_share_roles input:checked"))
        .map((el) => Number(el.value))
        .filter((value) => Number.isInteger(value) && value > 0);
    }

    function syncAreaAssistantSelects() {
      populateChannelSelect(getAcVal("ac_default_channel"));
      populateRoleSelect(getAcVal("ac_auto_role_id"), getAcVal("ac_auto_role_name"));
    }

    function onDefaultChannelSelectChange() {
      const el = AdminShell.byId("ac_default_channel_select");
      if (!el) return;
      setAcVal("ac_default_channel", el.value || "");
    }

    function onAutoRoleSelectChange() {
      const el = AdminShell.byId("ac_auto_role_select");
      if (!el) return;
      const option = el.options[el.selectedIndex];
      setAcVal("ac_auto_role_id", el.value || "");
      setAcVal("ac_auto_role_name", option ? (option.dataset.roleName || "") : "");
    }

    async function loadAreaRoles() {
      if (!currentArea) return;
      try {
        const data = await AdminShell.req(`/admin/api/areas/${encodeURIComponent(currentArea)}/meta`);
        areaRolesData = data.roles || [];
        populateRoleSelect(getAcVal("ac_auto_role_id"), getAcVal("ac_auto_role_name"));
        populateScreenShareRoles(window.__screenShareRoleIds || []);
      } catch (_) {
        areaRolesData = [];
        populateRoleSelect(getAcVal("ac_auto_role_id"), getAcVal("ac_auto_role_name"));
        populateScreenShareRoles([]);
      }
    }

    async function loadAreaConfig() {
      if (!currentArea) return;
      try {
        const data = await AdminShell.req(`/admin/api/area-configs/${encodeURIComponent(currentArea)}`);
        const c = data.config || {};
        setAcVal("ac_name", c.name || "");
        setAcVal("ac_default_channel", c.default_channel || "");
        setAcVal("ac_auto_role_id", c.auto_assign_role_id || "");
        setAcVal("ac_auto_role_name", c.auto_assign_role_name || "");
        setAcVal("ac_welcome", c.welcome_message || "");
        setAcVal("ac_leave", c.leave_message || "");
        setAcVal("ac_admin_uids", (c.admin_uids || []).join(", "));
        setAcVal("ac_plugins_enabled", (c.plugins_enabled || []).join(", "));
        setAcVal("ac_plugins_disabled", (c.plugins_disabled || []).join(", "));
        window.__screenShareRoleIds = c.screen_share_role_ids || [];
        populateScreenShareRoles(window.__screenShareRoleIds);
        const ann = c.use_announcement_style;
        const annVal = ann === true ? "true" : (ann === false ? "false" : "");
        setAcVal("ac_announcement_style", annVal);
        AdminShell.refreshCustomSelect("ac_announcement_style");
        syncAreaAssistantSelects();
        if (data.configured) {
          AdminShell.showMessage("areaConfigMsg", "当前域已有独立配置");
        } else {
          AdminShell.showMessage("areaConfigMsg", "当前域尚未配置，使用全局默认");
        }
      } catch (e) {
        AdminShell.showMessage("areaConfigMsg", "加载域配置失败: " + e.message, true);
      }
    }

    function splitList(val) {
      return val.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
    }

    async function saveAreaConfig() {
      if (!currentArea) return;
      const annStr = (AdminShell.byId("ac_announcement_style").value || "").trim();
      const annVal = annStr === "true" ? true : (annStr === "false" ? false : null);
      const body = {
        name: (AdminShell.byId("ac_name").value || "").trim(),
        default_channel: (AdminShell.byId("ac_default_channel").value || "").trim(),
        auto_assign_role_id: (AdminShell.byId("ac_auto_role_id").value || "").trim(),
        auto_assign_role_name: (AdminShell.byId("ac_auto_role_name").value || "").trim(),
        welcome_message: (AdminShell.byId("ac_welcome").value || "").trim(),
        leave_message: (AdminShell.byId("ac_leave").value || "").trim(),
        admin_uids: splitList(AdminShell.byId("ac_admin_uids").value || ""),
        plugins_enabled: splitList(AdminShell.byId("ac_plugins_enabled").value || ""),
        plugins_disabled: splitList(AdminShell.byId("ac_plugins_disabled").value || ""),
        screen_share_role_ids: selectedScreenShareRoles(),
        use_announcement_style: annVal,
      };
      try {
        await AdminShell.req(`/admin/api/area-configs/${encodeURIComponent(currentArea)}`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        AdminShell.showMessage("areaConfigMsg", "域配置已保存并持久化");
        setState("配置已保存", "success");
      } catch (e) {
        AdminShell.showMessage("areaConfigMsg", "保存失败: " + e.message, true);
      }
    }

    async function deleteAreaConfig() {
      if (!currentArea) return;
      if (!confirm("确认删除该域的独立配置？将回退到全局默认。")) return;
      try {
        await AdminShell.req(`/admin/api/area-configs/${encodeURIComponent(currentArea)}`, {
          method: "DELETE",
        });
        AdminShell.showMessage("areaConfigMsg", "域配置已删除，将使用全局默认");
        await loadAreaConfig();
      } catch (e) {
        AdminShell.showMessage("areaConfigMsg", "删除失败: " + e.message, true);
      }
    }

    // ---- Channels ----

    async function loadChannels() {
      if (!currentArea) return;
      var areaIdEl = AdminShell.byId("areaIdDisplay");
      if (areaIdEl) areaIdEl.textContent = currentArea;
      const tbody = AdminShell.byId("channelRows");
      try {
        const data = await AdminShell.req(`/admin/api/channels?area=${encodeURIComponent(currentArea)}`);
        channelsData = data.channels || [];
        populateChannelSelect(getAcVal("ac_default_channel"));
        if (!channelsData.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">暂无频道</td></tr>';
          return;
        }
        tbody.innerHTML = channelsData.map((ch) => {
          var t = (ch.type || "").toUpperCase();
          const typeClass = t === "VOICE" || t === "AUDIO"
            ? "a-ch-type--voice" : "a-ch-type--text";
          const typeLabel = typeClass.includes("voice") ? "语音" : "文字";
          var badges = `<span class="a-ch-type ${typeClass}">${typeLabel}</span>`;
          if (ch.secret) badges += ' <span class="a-ch-type a-ch-type--secret">私密</span>';
          return `<tr>
            <td>
              <div style="font-weight:600">${esc(ch.name)}</div>
              <div class="a-ch-id">${esc(ch.id)}</div>
            </td>
            <td style="color:var(--ink-soft);font-size:12px">${esc(ch.group)}</td>
            <td>${badges}</td>
            <td>
              <div class="a-ch-actions">
                <button class="btn btn-ghost" type="button" data-action="show-edit-channel" data-ch-id="${esc(ch.id)}" data-ch-type="${esc(ch.type)}">编辑</button>
                <button class="btn btn-danger" type="button" data-action="do-delete-channel" data-ch-id="${esc(ch.id)}" data-ch-name="${esc(ch.name)}">删除</button>
              </div>
            </td>
          </tr>`;
        }).join("");
      } catch (e) {
        channelsData = [];
        populateChannelSelect(getAcVal("ac_default_channel"));
        tbody.innerHTML = `<tr><td colspan="5" class="empty-state">加载失败: ${esc(e.message)}</td></tr>`;
      }
    }

    function esc(s) {
      return AdminShell.escapeHtml(s);
    }

    // ---- Create channel ----

    function showCreateChannel() {
      AdminShell.byId("newChName").value = "";
      AdminShell.byId("newChType").value = "text";
      AdminShell.showMessage("createChMsg", "");
      AdminShell.byId("chModalOverlay").classList.add("is-open");
      AdminShell.byId("chModalDialog").classList.add("is-open");
    }

    function closeChModal() {
      AdminShell.byId("chModalOverlay").classList.remove("is-open");
      AdminShell.byId("chModalDialog").classList.remove("is-open");
    }

    async function doCreateChannel() {
      const name = (AdminShell.byId("newChName").value || "").trim();
      const type = AdminShell.byId("newChType").value;
      if (!name) { AdminShell.showMessage("createChMsg", "频道名称不能为空", true); return; }
      AdminShell.showMessage("createChMsg", "");
      try {
        await AdminShell.req("/admin/api/channels/create", {
          method: "POST",
          body: JSON.stringify({ area: currentArea, name, type }),
        });
        closeChModal();
        await loadChannels();
        setState("频道已创建", "success");
      } catch (e) {
        AdminShell.showMessage("createChMsg", "创建失败: " + e.message, true);
      }
    }

    // ---- Edit channel ----

    var _editChType = "TEXT";
    var _selectedUids = new Set();
    var _onlineMembers = [];

    async function showEditChannel(id, chType) {
      _editChType = (chType || "TEXT").toUpperCase();
      _selectedUids = new Set();
      _onlineMembers = [];
      AdminShell.byId("editChId").value = id;
      AdminShell.showMessage("editChMsg", "加载中...");
      AdminShell.byId("editChOverlay").classList.add("is-open");
      AdminShell.byId("editChDialog").classList.add("is-open");

      var isVoice = _editChType === "VOICE" || _editChType === "AUDIO";
      AdminShell.byId("editChQualityWrap").style.display = isVoice ? "" : "none";
      AdminShell.byId("editChDelayWrap").style.display = isVoice ? "" : "none";
      AdminShell.byId("editChTitle").textContent = isVoice ? "编辑语音频道" : "编辑文字频道";

      try {
        var data = await AdminShell.req(`/admin/api/channels/${encodeURIComponent(id)}/settings`);
        var s = data.settings || {};
        AdminShell.byId("editChName").value = s.name || "";
        AdminShell.byId("editChMaxMember").value = s.maxMember || 30000;
        AdminShell.byId("editChTextGap").value = s.textGapSecond || 0;
        AdminShell.byId("editChVoiceQuality").value = s.voiceQuality || "64k";
        AdminShell.byId("editChVoiceDelay").value = s.voiceDelay || "LOW";
        AdminShell.byId("editChSecret").checked = !!s.secret;
        AdminShell.byId("editChHasPassword").checked = !!s.hasPassword;
        AdminShell.byId("editChPassword").value = s.password || "";
        toggleEditPwd();

        var [amData, olData] = await Promise.all([
          AdminShell.req(`/admin/api/channels/${encodeURIComponent(id)}/accessible-members`).catch(function() { return {members: []}; }),
          AdminShell.req(`/admin/api/online-members?area=${encodeURIComponent(currentArea)}`).catch(function() { return {members: []}; }),
        ]);
        (amData.members || []).forEach(function(m) { _selectedUids.add(m.uid); });
        _onlineMembers = olData.members || [];

        toggleSecretPanel();
        AdminShell.showMessage("editChMsg", "");
      } catch (e) {
        AdminShell.showMessage("editChMsg", "加载设置失败: " + e.message, true);
      }
    }

    function toggleEditPwd() {
      var show = AdminShell.byId("editChHasPassword").checked;
      AdminShell.byId("editChPwdWrap").style.display = show ? "" : "none";
    }

    function toggleSecretPanel() {
      var show = AdminShell.byId("editChSecret").checked;
      AdminShell.byId("editChAccessWrap").style.display = show ? "" : "none";
      if (show) renderOnlineMembers();
    }

    function renderOnlineMembers() {
      var el = AdminShell.byId("editChAccessList");
      if (!_onlineMembers.length) {
        el.innerHTML = '<span class="a-am-empty">当前无在线成员</span>';
        return;
      }
      el.innerHTML = _onlineMembers.map(function(m) {
        var checked = _selectedUids.has(m.uid) ? " checked" : "";
        return '<label class="a-am-item">'
          + '<input type="checkbox" data-change="access-member" data-uid="' + esc(m.uid) + '"' + checked + ' />'
          + '<span class="a-am-dot"></span>'
          + '<span class="a-am-name">' + esc(m.name) + '</span>'
          + '</label>';
      }).join("");
    }

    function toggleAccessMember(uid, add) {
      if (add) _selectedUids.add(uid);
      else _selectedUids.delete(uid);
    }

    function closeEditChannel() {
      AdminShell.byId("editChOverlay").classList.remove("is-open");
      AdminShell.byId("editChDialog").classList.remove("is-open");
    }

    async function doSaveChannelSettings() {
      var id = AdminShell.byId("editChId").value;
      var name = (AdminShell.byId("editChName").value || "").trim();
      if (!name) { AdminShell.showMessage("editChMsg", "频道名称不能为空", true); return; }

      var body = {
        area: currentArea,
        name: name,
        maxMember: parseInt(AdminShell.byId("editChMaxMember").value, 10) || 30000,
        textGapSecond: parseInt(AdminShell.byId("editChTextGap").value, 10) || 0,
        secret: AdminShell.byId("editChSecret").checked,
        hasPassword: AdminShell.byId("editChHasPassword").checked,
        password: AdminShell.byId("editChHasPassword").checked
          ? (AdminShell.byId("editChPassword").value || "") : "",
      };

      if (body.secret) {
        body.accessibleMembers = Array.from(_selectedUids);
      }

      var isVoice = _editChType === "VOICE" || _editChType === "AUDIO";
      if (isVoice) {
        body.voiceQuality = AdminShell.byId("editChVoiceQuality").value;
        body.voiceDelay = AdminShell.byId("editChVoiceDelay").value;
      }

      AdminShell.showMessage("editChMsg", "");
      try {
        await AdminShell.req(`/admin/api/channels/${encodeURIComponent(id)}/settings`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        closeEditChannel();
        await loadChannels();
        setState("频道设置已保存", "success");
      } catch (e) {
        AdminShell.showMessage("editChMsg", "保存失败: " + e.message, true);
      }
    }

    // ---- Delete channel ----

    async function doDeleteChannel(id, name) {
      if (!confirm(`确认删除频道「${name}」？此操作不可撤销。`)) return;
      try {
        await AdminShell.req(`/admin/api/channels/${encodeURIComponent(id)}`, {
          method: "DELETE",
          body: JSON.stringify({ area: currentArea }),
        });
        await loadChannels();
        setState("频道已删除", "success");
      } catch (e) {
        setState("删除失败: " + e.message, "error");
      }
    }

    // ---- Voice channels ----

    async function loadVoiceChannels() {
      if (!currentArea) return;
      const container = AdminShell.byId("voiceList");
      try {
        const data = await AdminShell.req(`/admin/api/voice-channels?area=${encodeURIComponent(currentArea)}`);
        const vcs = data.voice_channels || [];
        voiceChannelsData = vcs;
        if (!vcs.length) {
          container.innerHTML = '<p class="empty-state">暂无语音频道数据</p>';
          return;
        }
        container.innerHTML = vcs.map((vc) => {
          const users = (vc.users || []).map((u) => {
            const avatar = u.avatar
              ? `<img class="a-voice-user__avatar" src="${esc(u.avatar)}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'a-voice-user__avatar a-voice-user__avatar--ph',textContent:'?'}))">`
              : `<span class="a-voice-user__avatar a-voice-user__avatar--ph">${esc((u.name || "?").slice(0, 1))}</span>`;
            return `<span class="a-voice-user">
              <span class="a-voice-user__ava">
                ${avatar}
                <span class="a-voice-user__dot"></span>
              </span>
              <span class="a-voice-user__name">${esc(u.name)}</span>
              <button class="a-voice-user__move" type="button" title="调度到其他语音频道"
                data-action="dispatch-user" data-uid="${esc(u.uid)}"
                data-name="${esc(u.name)}" data-from="${esc(vc.id)}">调度</button>
            </span>`;
          }).join("");
          return `<div class="a-voice-ch">
            <div class="a-voice-ch__head">
              <span class="a-voice-ch__name">${esc(vc.name)}</span>
              <span class="a-voice-ch__group">${esc(vc.group)}</span>
              <span class="a-voice-ch__count">${vc.users.length} 人</span>
            </div>
            <div class="a-voice-users">${users || '<span style="font-size:12px;color:var(--ink-faint)">无用户在线</span>'}</div>
          </div>`;
        }).join("");
      } catch (e) {
        container.innerHTML = `<p class="empty-state">加载失败: ${esc(e.message)}</p>`;
      }
    }

    // ---- Dispatch member to another voice channel ----

    function showDispatch(uid, name, fromCh) {
      const targets = voiceChannelsData.filter((vc) => vc.id !== fromCh);
      const sel = AdminShell.byId("dispatchTarget");
      sel.innerHTML = targets.length
        ? targets.map((vc) =>
            `<option value="${vc.id}">${esc(vc.name)}${vc.group ? " · " + esc(vc.group) : ""}</option>`
          ).join("")
        : '<option value="">无其他语音频道</option>';
      AdminShell.byId("dispatchUid").value = uid;
      AdminShell.byId("dispatchFrom").value = fromCh || "";
      const fromVc = voiceChannelsData.find((vc) => vc.id === fromCh);
      AdminShell.byId("dispatchInfo").textContent =
        `将「${name}」从「${fromVc ? fromVc.name : "当前频道"}」调度到：`;
      AdminShell.showMessage("dispatchMsg", targets.length ? "" : "当前域没有其他语音频道可调度", !targets.length);
      AdminShell.upgradeSelect("dispatchTarget");
      AdminShell.byId("dispatchOverlay").classList.add("is-open");
      AdminShell.byId("dispatchDialog").classList.add("is-open");
    }

    function closeDispatch() {
      AdminShell.byId("dispatchOverlay").classList.remove("is-open");
      AdminShell.byId("dispatchDialog").classList.remove("is-open");
    }

    async function doDispatch() {
      const uid = AdminShell.byId("dispatchUid").value;
      const from = AdminShell.byId("dispatchFrom").value;
      const to = AdminShell.byId("dispatchTarget").value;
      if (!to) { AdminShell.showMessage("dispatchMsg", "请选择目标语音频道", true); return; }
      AdminShell.showMessage("dispatchMsg", "调度中...");
      try {
        await AdminShell.req("/admin/api/voice-channels/dispatch", {
          method: "POST",
          body: JSON.stringify({ area: currentArea, target: uid, to_channel: to, from_channel: from }),
        });
        closeDispatch();
        await loadVoiceChannels();
        setState("已调度", "success");
      } catch (e) {
        AdminShell.showMessage("dispatchMsg", "调度失败: " + e.message, true);
      }
    }

    AdminShell.registerActions({
      "refresh-areas": () => loadAreaManager(),
      "refresh-area-invites": () => loadAreaInvites(),
      "accept-area-invite": (el) => acceptAreaInvite(el.dataset.code),
      "reject-area-invite": (el) => rejectAreaInvite(el.dataset.code),
      "leave-current-area": () => leaveCurrentArea(),
      "save-area-config": () => saveAreaConfig(),
      "delete-area-config": () => deleteAreaConfig(),
      "show-create-channel": () => showCreateChannel(),
      "load-voice-channels": () => loadVoiceChannels(),
      "dispatch-user": (el) => showDispatch(el.dataset.uid, el.dataset.name, el.dataset.from),
      "close-dispatch": () => closeDispatch(),
      "do-dispatch": () => doDispatch(),
      "close-ch-modal": () => closeChModal(),
      "do-create-channel": () => doCreateChannel(),
      "close-edit-channel": () => closeEditChannel(),
      "do-save-channel-settings": () => doSaveChannelSettings(),
      "show-edit-channel": (el) => showEditChannel(el.dataset.chId, el.dataset.chType),
      "do-delete-channel": (el) => doDeleteChannel(el.dataset.chId, el.dataset.chName),
      "area-change": () => onAreaChange(),
      "default-channel-change": () => onDefaultChannelSelectChange(),
      "auto-role-change": () => onAutoRoleSelectChange(),
      "toggle-secret-panel": () => toggleSecretPanel(),
      "toggle-edit-pwd": () => toggleEditPwd(),
      "access-member": (el) => toggleAccessMember(el.dataset.uid, el.checked),
    });
    AdminShell.upgradeSelect("ac_default_channel_select");
    AdminShell.upgradeSelect("ac_auto_role_select");
    AdminShell.upgradeSelect("ac_announcement_style");
    AdminShell.upgradeSelect("newChType");
    AdminShell.upgradeSelect("editChVoiceQuality");
    AdminShell.upgradeSelect("editChVoiceDelay");
    AdminShell.upgradeSelect("dispatchTarget");
    AdminShell.bootstrapAuth({
      page: "areas",
      loggedInText: "已登录域管理",
      onLogin: () => loadAreaManager(),
      onLoggedOut: () => setState("等待操作", "warning"),
      onLoginError: () => setState("登录失败", "error"),
    });
