    let _cfgPluginName = "";

    function esc(s) { return AdminShell.escapeHtml(s); }

    function setState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setStatus(text, variant, "pluginState");
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录插件管理",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadPlugins();
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

    // ---- Plugin list ----

    async function loadPlugins() {
      const loadedTbody = AdminShell.byId("loadedRows");
      const availTbody = AdminShell.byId("availableRows");
      const availCard = AdminShell.byId("availableCard");
      try {
        const data = await AdminShell.req("/admin/api/plugins");
        const loaded = data.loaded || [];
        const available = data.available || [];

        AdminShell.byId("loadedCount").textContent = String(data.loaded_count || loaded.length);
        AdminShell.byId("availableCount").textContent = String(data.available_count || available.length);

        if (!loaded.length) {
          loadedTbody.innerHTML = '<tr><td colspan="6" class="empty-state">暂无已加载插件</td></tr>';
        } else {
          loadedTbody.innerHTML = loaded.map(function (p) {
            var typeTag = p.builtin
              ? '<span class="p-tag p-tag--builtin">内置</span>'
              : '<span class="p-tag p-tag--ext">扩展</span>';
            var cmds = [];
            (p.mention_prefixes || []).forEach(function (px) { cmds.push("<code>" + esc(px) + "</code>"); });
            (p.slash_commands || []).forEach(function (c) { cmds.push("<code>/" + esc(c) + "</code>"); });
            var cmdsHtml = cmds.length ? '<div class="p-cmds">' + cmds.join("") + "</div>" : '<span style="color:var(--ink-faint);font-size:12px">-</span>';

            var actions = [];
            if (!p.builtin) {
              actions.push('<button class="btn btn-danger" onclick="unloadPlugin(\'' + esc(p.name) + '\')">卸载</button>');
            }
            actions.push('<button class="btn btn-ghost" onclick="reloadConfig(\'' + esc(p.name) + '\')">重载配置</button>');
            actions.push('<button class="btn btn-ghost" onclick="openConfigEditor(\'' + esc(p.name) + '\')">编辑配置</button>');

            return '<tr>' +
              '<td style="font-weight:600">' + esc(p.name) + '</td>' +
              '<td style="font-size:12px;color:var(--ink-soft)">' + esc(p.description || "") + '</td>' +
              '<td style="font-size:12px">' + esc(p.version || "") + '</td>' +
              '<td>' + typeTag + '</td>' +
              '<td>' + cmdsHtml + '</td>' +
              '<td><div class="p-actions">' + actions.join("") + '</div></td>' +
              '</tr>';
          }).join("");
        }

        if (available.length) {
          availCard.style.display = "";
          availTbody.innerHTML = available.map(function (name) {
            return '<tr>' +
              '<td style="font-weight:600">' + esc(name) + '</td>' +
              '<td><div class="p-actions"><button class="btn btn-primary" onclick="loadPlugin(\'' + esc(name) + '\')">加载</button></div></td>' +
              '</tr>';
          }).join("");
        } else {
          availCard.style.display = "none";
        }

        setState("已同步", "success");
      } catch (e) {
        loadedTbody.innerHTML = '<tr><td colspan="6" class="empty-state">加载失败: ' + esc(e.message) + '</td></tr>';
        setState("加载失败", "error");
      }
    }

    // ---- Plugin operations ----

    async function loadPlugin(name) {
      try {
        await AdminShell.req("/admin/api/plugins/" + encodeURIComponent(name) + "/load", {
          method: "POST", body: "{}",
        });
        setState("已加载: " + name, "success");
        await loadPlugins();
      } catch (e) {
        setState("加载失败: " + e.message, "error");
      }
    }

    async function unloadPlugin(name) {
      if (!confirm("确认卸载插件「" + name + "」？")) return;
      try {
        await AdminShell.req("/admin/api/plugins/" + encodeURIComponent(name) + "/unload", {
          method: "POST", body: "{}",
        });
        setState("已卸载: " + name, "success");
        await loadPlugins();
      } catch (e) {
        setState("卸载失败: " + e.message, "error");
      }
    }

    async function reloadConfig(name) {
      try {
        await AdminShell.req("/admin/api/plugins/" + encodeURIComponent(name) + "/reload-config", {
          method: "POST", body: "{}",
        });
        setState("配置已重载: " + name, "success");
      } catch (e) {
        setState("重载失败: " + e.message, "error");
      }
    }

    // ---- Config editor ----

    async function openConfigEditor(name) {
      _cfgPluginName = name;
      AdminShell.byId("cfgTitle").textContent = "编辑配置 - " + name;
      AdminShell.byId("cfgEditor").value = "加载中...";
      AdminShell.showMessage("cfgMsg", "");
      AdminShell.byId("cfgSchemaHint").style.display = "none";
      AdminShell.byId("cfgOverlay").classList.add("is-open");
      AdminShell.byId("cfgDialog").classList.add("is-open");

      try {
        var data = await AdminShell.req("/admin/api/plugins/" + encodeURIComponent(name) + "/config");
        AdminShell.byId("cfgEditor").value = JSON.stringify(data.config || {}, null, 2);
        if (data.schema) {
          var hint = AdminShell.byId("cfgSchemaHint");
          hint.textContent = "Schema: " + JSON.stringify(data.schema, null, 2);
          hint.style.display = "";
        }
      } catch (e) {
        AdminShell.byId("cfgEditor").value = "{}";
        AdminShell.showMessage("cfgMsg", "读取配置失败: " + e.message, true);
      }
    }

    function closeConfigEditor() {
      AdminShell.byId("cfgOverlay").classList.remove("is-open");
      AdminShell.byId("cfgDialog").classList.remove("is-open");
      _cfgPluginName = "";
    }

    async function saveConfig() {
      if (!_cfgPluginName) return;
      var raw = AdminShell.byId("cfgEditor").value;
      var parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (e) {
        AdminShell.showMessage("cfgMsg", "JSON 格式无效: " + e.message, true);
        return;
      }
      AdminShell.showMessage("cfgMsg", "");
      try {
        var resp = await AdminShell.req("/admin/api/plugins/" + encodeURIComponent(_cfgPluginName) + "/config", {
          method: "POST",
          body: JSON.stringify({ config: parsed }),
        });
        var msg = "配置已保存";
        if (resp.reload) msg += " (" + resp.reload + ")";
        AdminShell.showMessage("cfgMsg", msg);
        setState("配置已保存: " + _cfgPluginName, "success");
      } catch (e) {
        AdminShell.showMessage("cfgMsg", "保存失败: " + e.message, true);
      }
    }

    AdminShell.init({ page: "plugins", passwordHandler: login });
    check();
