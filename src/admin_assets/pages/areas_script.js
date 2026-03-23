    let currentArea = "";
    let channelsData = [];

    function setState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setStatus(text, variant, "areaState");
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录域管理",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadAreaManager();
      } catch (_) {
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        AdminShell.showMessage("loginMsg", "");
        setState("等待操作", "warning");
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
        setState("登录失败", "error");
      }
    }

    async function logout() {
      try {
        await AdminShell.req("/admin/api/logout", { method: "POST", body: "{}" });
      } catch (_) {}
      await check();
    }

    async function loadAreaManager() {
      await loadAreas();
      if (currentArea) {
        await Promise.all([loadAreaConfig(), loadChannels(), loadVoiceChannels()]);
      }
      setState("已同步", "success");
    }

    async function loadAreas() {
      const picker = AdminShell.byId("areaPicker");
      try {
        const data = await AdminShell.req("/admin/api/areas");
        const areas = data.areas || [];
        picker.innerHTML = areas.length
          ? areas.map((a) => `<option value="${a.id}">${a.name || a.id}</option>`).join("")
          : '<option value="">无可用域</option>';
        if (!currentArea && areas.length) {
          currentArea = areas[0].id;
        }
        if (currentArea) {
          picker.value = currentArea;
        }
      } catch (e) {
        picker.innerHTML = '<option value="">加载失败</option>';
      }
      AdminShell.upgradeSelect("areaPicker");
    }

    function onAreaChange() {
      currentArea = AdminShell.byId("areaPicker").value;
      if (currentArea) {
        Promise.all([loadAreaConfig(), loadChannels(), loadVoiceChannels()]);
      }
    }

    // ---- Area config ----

    function setAcVal(id, value) {
      const el = AdminShell.byId(id);
      if (!el) return;
      if (el.type === "checkbox") el.checked = !!value;
      else el.value = value ?? "";
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
        setAcVal("ac_profanity", c.profanity_enabled !== false);
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
        profanity_enabled: !!AdminShell.byId("ac_profanity").checked,
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
                <button class="btn btn-ghost" onclick="showEditChannel('${esc(ch.id)}','${esc(ch.type)}')">编辑</button>
                <button class="btn btn-danger" onclick="doDeleteChannel('${esc(ch.id)}','${esc(ch.name)}')">删除</button>
              </div>
            </td>
          </tr>`;
        }).join("");
      } catch (e) {
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
          + '<input type="checkbox" onchange="toggleAccessMember(\'' + esc(m.uid) + '\', this.checked)"' + checked + ' />'
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
        if (!vcs.length) {
          container.innerHTML = '<p class="empty-state">暂无语音频道数据</p>';
          return;
        }
        container.innerHTML = vcs.map((vc) => {
          const users = (vc.users || []).map((u) =>
            `<span class="a-voice-user"><span class="a-voice-user__dot"></span>${esc(u.name)}</span>`
          ).join("");
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

    AdminShell.init({ page: "areas", passwordHandler: login });
    AdminShell.upgradeSelect("newChType");
    AdminShell.upgradeSelect("editChVoiceQuality");
    AdminShell.upgradeSelect("editChVoiceDelay");
    check();
