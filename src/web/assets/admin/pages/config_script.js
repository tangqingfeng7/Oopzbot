    /* ---- Keyword editor helpers ---- */
    window._kwRender = function(obj) {
      var list = AdminShell.byId("cfg_kw_list");
      if (!list) return;
      list.innerHTML = "";
      Object.entries(obj).forEach(function(pair) { _kwAddRow(list, pair[0], pair[1]); });
    };
    function _kwAddRow(list, key, val) {
      var row = document.createElement("div");
      row.className = "kw-row";
      row.innerHTML =
        '<input class="kw-key" type="text" placeholder="关键词" value="' + AdminShell.escapeHtml(key) + '">' +
        '<input class="kw-val" type="text" placeholder="回复内容" value="' + AdminShell.escapeHtml(val) + '">' +
        '<button type="button" class="kw-del" title="删除">&times;</button>';
      row.querySelector(".kw-del").onclick = function() { row.remove(); };
      list.appendChild(row);
    }
    window._kwAdd = function() {
      var list = AdminShell.byId("cfg_kw_list");
      if (!list) return;
      _kwAddRow(list, "", "");
      var last = list.querySelector(".kw-row:last-child .kw-key");
      if (last) last.focus();
    };
    window._kwCollect = function() {
      var obj = {};
      var list = AdminShell.byId("cfg_kw_list");
      if (!list) return obj;
      list.querySelectorAll(".kw-row").forEach(function(row) {
        var k = row.querySelector(".kw-key").value.trim();
        var v = row.querySelector(".kw-val").value;
        if (k) obj[k] = v;
      });
      return obj;
    };

    function setVal(id, value) {
      const element = AdminShell.byId(id);
      if (!element) {
        return;
      }
      if (element.type === "checkbox") {
        element.checked = !!value;
      } else {
        element.value = value ?? "";
      }
    }

    function getInt(id) {
      const value = Number(AdminShell.byId(id).value);
      return Number.isFinite(value) ? Math.trunc(value) : 0;
    }

    function getFloat(id) {
      const value = Number(AdminShell.byId(id).value);
      return Number.isFinite(value) ? value : 0;
    }

    function val(id) {
      return (AdminShell.byId(id).value || "").trim();
    }

    function chk(id) {
      return !!AdminShell.byId(id).checked;
    }

    // ---- OOPZ 代理：单字符串配置 <-> 「开关 + 协议 + 地址 + 端口」 ----
    // oopz.proxy 语义：""=系统/未启用、"direct"/false=直连、url 或别名(clash...)=启用。
    const PROXY_DEFAULT_HOST = "127.0.0.1";
    const PROXY_HTTP_PORT = 7890;
    const PROXY_SOCKS_PORT = 7891;
    const PROXY_ALIASES = {
      "clash": "http://127.0.0.1:7890",
      "clash-http": "http://127.0.0.1:7890",
      "clash-mixed": "http://127.0.0.1:7890",
      "clash-socks": "socks5://127.0.0.1:7891",
      "mihomo": "http://127.0.0.1:7890",
      "mihomo-socks": "socks5://127.0.0.1:7891",
    };

    // mode: "direct"=直连忽略环境、"system"=跟随系统/环境变量代理、"manual"=手动指定。
    function _parseProxyValue(raw) {
      const out = { mode: "direct", scheme: "http", host: PROXY_DEFAULT_HOST, port: PROXY_HTTP_PORT };
      if (raw === false) {
        return out;
      }
      const value = (raw == null ? "" : String(raw)).trim();
      if (value === "") {
        out.mode = "system";
        return out;
      }
      if (value.toLowerCase() === "direct") {
        return out;
      }
      let urlStr = PROXY_ALIASES[value.toLowerCase()] || value;
      if (urlStr.indexOf("://") === -1) {
        urlStr = "http://" + urlStr;
      }
      const m = urlStr.match(/^([a-zA-Z0-9]+):\/\/(?:[^@/]*@)?([^:/\s]+)(?::(\d+))?/);
      if (!m) {
        return out;
      }
      out.mode = "manual";
      out.scheme = m[1].toLowerCase().indexOf("socks") === 0 ? "socks5" : "http";
      out.host = m[2] || PROXY_DEFAULT_HOST;
      out.port = m[3] ? Number(m[3]) : (out.scheme === "socks5" ? PROXY_SOCKS_PORT : PROXY_HTTP_PORT);
      return out;
    }

    function _applyProxyModeState() {
      const manual = val("cfg_proxy_mode") === "manual";
      document.querySelectorAll(".js-proxy-detail").forEach(function (el) {
        el.hidden = !manual;
      });
    }

    function _loadProxy(config) {
      const p = _parseProxyValue(config && config.oopz ? config.oopz.proxy : "");
      setVal("cfg_proxy_mode", p.mode);
      setVal("cfg_proxy_scheme", p.scheme);
      setVal("cfg_proxy_host", p.host);
      setVal("cfg_proxy_port", p.port);
      AdminShell.refreshCustomSelect("cfg_proxy_mode");
      AdminShell.refreshCustomSelect("cfg_proxy_scheme");
      _applyProxyModeState();
    }

    function _buildProxyValue() {
      const mode = val("cfg_proxy_mode") || "direct";
      if (mode === "system") {
        return "";
      }
      if (mode !== "manual") {
        return "direct";
      }
      const scheme = val("cfg_proxy_scheme") || "http";
      const host = val("cfg_proxy_host") || PROXY_DEFAULT_HOST;
      const port = getInt("cfg_proxy_port") || (scheme === "socks5" ? PROXY_SOCKS_PORT : PROXY_HTTP_PORT);
      return scheme + "://" + host + ":" + port;
    }

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
    }

    function renderMusicAreaHint(info) {
      const hint = AdminShell.byId("cfg_oopz_area_hint");
      if (!hint) {
        return;
      }
      const area = info.area || "-";
      const sourceText = info.source_text || "未解析";
      const activeArea = info.active_area || "-";
      const defaultArea = info.default_area || "-";
      hint.textContent = "当前音乐域：" + area + "；来源：" + sourceText + "；活跃域：" + activeArea + "；默认域：" + defaultArea;
    }

    // 扫码登录通用控制器：网易云 / B 站共用同一套二维码刷新、轮询、
    // 账号状态与 Cookie 回填逻辑，仅通过 config 注入各自的 DOM id、
    // 接口端点和文案差异。
    function createQrLoginController(config) {
      let timer = null;
      let key = "";
      let baseUrl = "";

      function setStatus(text, isError) {
        const element = AdminShell.byId(config.ids.status);
        if (!element) {
          return;
        }
        element.textContent = text || "";
        element.style.color = isError ? "var(--danger)" : "var(--ink-faint)";
      }

      function accountText(profile, message) {
        if (profile && profile.user_id) {
          const nickname = profile.nickname || "未命名账号";
          return config.accountLabel + nickname + "（ID：" + profile.user_id + "）";
        }
        return message || config.accountLabel + "已登录，账号信息待保存后刷新";
      }

      function renderAccount(profile, message, isError) {
        const targets = Array.from(document.querySelectorAll(config.accountSelector));
        if (!targets.length) {
          return;
        }
        let text;
        let color;
        if (profile && profile.user_id) {
          text = config.accountLabel + (profile.nickname || "未命名账号") + "（ID：" + profile.user_id + "）";
          color = "var(--success)";
        } else {
          text = config.accountLabel + (message || "未登录");
          color = isError ? "var(--danger)" : "var(--ink-faint)";
        }
        targets.forEach(function (element) {
          element.textContent = text;
          element.style.color = color;
        });
      }

      async function loadAccountStatus(configured) {
        if (!configured) {
          renderAccount(null, "未登录", false);
          return;
        }
        renderAccount(null, "检测中...", false);
        try {
          const data = await AdminShell.req(config.endpoints.account);
          if (data.logged_in) {
            renderAccount(data.profile || null, "", false);
          } else {
            renderAccount(null, data.message || "未登录或 Cookie 已过期", false);
          }
        } catch (error) {
          renderAccount(null, error.message || "账号状态检测失败", true);
        }
      }

      function setSaveEnabled(enabled) {
        const runtimeButton = AdminShell.byId(config.ids.saveBtn);
        if (runtimeButton) {
          runtimeButton.disabled = !enabled;
        }
      }

      function stopPolling() {
        if (timer) {
          window.clearInterval(timer);
          timer = null;
        }
      }

      function resetView(text) {
        const image = AdminShell.byId(config.ids.img);
        const empty = AdminShell.byId(config.ids.empty);
        const link = AdminShell.byId(config.ids.link);
        if (image) {
          image.hidden = true;
          image.removeAttribute("src");
        }
        if (empty) {
          empty.hidden = false;
          empty.textContent = text || "等待刷新";
        }
        if (link) {
          link.hidden = true;
          link.href = "#";
        }
      }

      function fillCookie(cookie) {
        setSecretValue(config.ids.cookie, cookie, true);
        setSaveEnabled(!!cookie);
      }

      async function check() {
        if (!key) {
          stopPolling();
          return;
        }
        try {
          const data = await AdminShell.req(config.endpoints.check, {
            method: "POST",
            body: config.buildCheckBody({ key: key, baseUrl: baseUrl }),
          });
          if (data.status === "waiting") {
            setStatus(data.message || "等待扫码", false);
            return;
          }
          if (data.status === "scanned") {
            setStatus(data.message || "已扫码，请在手机上确认", false);
            return;
          }
          if (data.status === "expired") {
            stopPolling();
            key = "";
            setStatus(data.message || "二维码已过期", true);
            resetView("已过期");
            setPageState(config.platform + "二维码过期", "warning");
            return;
          }
          if (data.status === "success") {
            stopPolling();
            key = "";
            fillCookie(data.cookie || "");
            const profileMessage = data.profile_message || "";
            renderAccount(data.profile || null, profileMessage || "已登录，账号信息待保存后刷新", false);
            setStatus("登录成功，Cookie 已填入", false);
            AdminShell.showMessage(
              "msg",
              config.buildSuccessMessage(
                data.profile || null,
                profileMessage,
                accountText(data.profile || null, profileMessage)
              )
            );
            setPageState(config.platform + "登录成功", "success");
            return;
          }
          setStatus(data.message || config.waitingDefault, false);
        } catch (error) {
          stopPolling();
          key = "";
          setStatus(error.message || "登录状态检查失败", true);
          setPageState(config.platform + "登录检查失败", "error");
        }
      }

      async function refresh() {
        const button = AdminShell.byId(config.ids.refreshBtn);
        stopPolling();
        key = "";
        baseUrl = "";
        setSaveEnabled(false);
        resetView("刷新中");
        setStatus("正在获取二维码...", false);
        setPageState(config.platform + "二维码刷新中", "warning");
        if (button) {
          button.disabled = true;
          button.textContent = "刷新中...";
        }
        try {
          const data = await AdminShell.req(config.endpoints.refresh, {
            method: "POST",
            body: config.buildRefreshBody(),
          });
          key = data.key || "";
          baseUrl = config.resolveBaseUrl ? config.resolveBaseUrl(data) : "";
          const image = AdminShell.byId(config.ids.img);
          const empty = AdminShell.byId(config.ids.empty);
          const link = AdminShell.byId(config.ids.link);
          if (image && data.qrimg) {
            image.src = data.qrimg;
            image.hidden = false;
          }
          if (empty) {
            empty.hidden = !!data.qrimg;
            empty.textContent = data.qrimg ? "" : "二维码链接已生成";
          }
          if (link && data.qrurl) {
            link.href = data.qrurl;
            link.hidden = false;
          }
          setStatus(data.message || "等待扫码", false);
          timer = window.setInterval(check, 2500);
          window.setTimeout(check, 900);
        } catch (error) {
          resetView("刷新失败");
          setStatus(error.message || "二维码刷新失败", true);
          setPageState(config.platform + "二维码刷新失败", "error");
        } finally {
          if (button) {
            button.disabled = false;
            button.textContent = "刷新二维码";
          }
        }
      }

      async function save() {
        if (!val(config.ids.cookie)) {
          setStatus("请先完成扫码登录", true);
          return;
        }
        await saveConfig(true);
      }

      return {
        renderAccount: renderAccount,
        loadAccountStatus: loadAccountStatus,
        setSaveEnabled: setSaveEnabled,
        check: check,
        refresh: refresh,
        save: save,
      };
    }

    const neteaseQr = createQrLoginController({
      platform: "网易云",
      accountLabel: "当前网易云账号：",
      accountSelector: "[data-netease-account-status]",
      waitingDefault: "等待网易云返回登录状态",
      ids: {
        status: "cfg_netease_qr_status",
        img: "cfg_netease_qr_img",
        empty: "cfg_netease_qr_empty",
        link: "cfg_netease_qr_link",
        refreshBtn: "cfg_netease_qr_refresh",
        saveBtn: "cfg_netease_qr_save_runtime",
        cookie: "cfg_netease_cookie",
      },
      endpoints: {
        refresh: "/admin/api/netease/login/qr",
        check: "/admin/api/netease/login/qr/check",
        account: "/admin/api/netease/account",
      },
      buildRefreshBody: function () {
        return JSON.stringify({ base_url: val("cfg_netease_base_url") });
      },
      resolveBaseUrl: function (data) {
        return data.base_url || val("cfg_netease_base_url");
      },
      buildCheckBody: function (state) {
        return JSON.stringify({
          base_url: state.baseUrl || val("cfg_netease_base_url"),
          key: state.key,
        });
      },
      buildSuccessMessage: function () {
        return "网易云 Cookie 已填入，可选择保存方式";
      },
    });

    const bilibiliQr = createQrLoginController({
      platform: "B 站",
      accountLabel: "当前B站账号：",
      accountSelector: "[data-bilibili-account-status]",
      waitingDefault: "等待 B 站返回登录状态",
      ids: {
        status: "cfg_bilibili_qr_status",
        img: "cfg_bilibili_qr_img",
        empty: "cfg_bilibili_qr_empty",
        link: "cfg_bilibili_qr_link",
        refreshBtn: "cfg_bilibili_qr_refresh",
        saveBtn: "cfg_bilibili_qr_save_runtime",
        cookie: "cfg_bilibili_cookie",
      },
      endpoints: {
        refresh: "/admin/api/bilibili/login/qr",
        check: "/admin/api/bilibili/login/qr/check",
        account: "/admin/api/bilibili/account",
      },
      buildRefreshBody: function () {
        return "{}";
      },
      buildCheckBody: function (state) {
        return JSON.stringify({ key: state.key });
      },
      buildSuccessMessage: function (profile, profileMessage, accountText) {
        return "B 站 Cookie 已填入，可选择保存方式；" + accountText;
      },
    });

    // 以下全局包装函数供 config_content.html 内联 onclick 调用。
    function loadNeteaseAccountStatus(configured) {
      return neteaseQr.loadAccountStatus(configured);
    }

    function refreshNeteaseQr() {
      return neteaseQr.refresh();
    }

    function saveNeteaseQrCookie(persist) {
      return neteaseQr.save(persist);
    }

    function loadBilibiliAccountStatus(configured) {
      return bilibiliQr.loadAccountStatus(configured);
    }

    function refreshBilibiliQr() {
      return bilibiliQr.refresh();
    }

    function saveBilibiliQrCookie(persist) {
      return bilibiliQr.save(persist);
    }

    function setSecretState(id, configured) {
      const element = AdminShell.byId(id);
      if (!element) {
        return;
      }
      element.type = "password";
      element.value = "";
      element.placeholder = configured ? "已配置，留空表示不修改" : "未配置";
      resetSecretToggle(element, id);
    }

    function setSecretValue(id, value, configured) {
      const element = AdminShell.byId(id);
      if (!element) {
        return;
      }
      element.type = "password";
      element.value = value || "";
      element.placeholder = configured && !value ? "已配置，留空表示不修改" : "";
      resetSecretToggle(element, id);
    }

    // 仅复位该字段自己的「显示/隐藏」切换按钮；避免误改同容器内的其它按钮
    // （如 OOPZ 登录区与密码框共用容器的「登录并获取」按钮）。
    function resetSecretToggle(element, id) {
      const container = element.parentElement;
      if (!container) {
        return;
      }
      const button = container.querySelector(
        'button[data-action="toggle-secret"][data-secret="' + id + '"]'
      );
      if (button) {
        button.textContent = "显示";
      }
    }

    function toggleSecret(id, button) {
      const element = AdminShell.byId(id);
      if (!element) {
        return;
      }
      const show = element.type === "password";
      element.type = show ? "text" : "password";
      if (button) {
        button.textContent = show ? "隐藏" : "显示";
      }
    }

    function setOopzLoginStatus(text, variant) {
      const element = AdminShell.byId("cfg_oopz_login_status");
      if (!element) {
        return;
      }
      const state = variant || "neutral";
      element.textContent = text;
      element.classList.toggle("is-error", state === "error");
      element.classList.toggle("is-success", state === "success");
    }

    function setOopzLoginButtonLoading(loading) {
      const button = AdminShell.byId("cfg_oopz_login_btn");
      if (!button) {
        return;
      }
      button.disabled = !!loading;
      button.textContent = loading ? "登录中..." : "登录并获取";
    }

    function formatOopzCredentialSummary(credentials) {
      const c = credentials || {};
      const expires = c.expires_at ? "；Token 到期：" + c.expires_at : "";
      return "已获取 UID " + (c.person_uid || "-") + "，设备 " + (c.device_id || "-") + expires;
    }

    async function loginOopzAccount() {
      const phone = val("cfg_oopz_login_phone");
      const passwordElement = AdminShell.byId("cfg_oopz_login_password");
      const password = passwordElement ? passwordElement.value : "";

      setOopzLoginButtonLoading(true);
      setOopzLoginStatus((!phone && !password) ? "正在使用配置中的 OOPZ 账号密码登录..." : "正在登录 OOPZ...", "neutral");
      setPageState("OOPZ 登录中", "warning");

      try {
        const data = await AdminShell.req("/admin/api/oopz/login", {
          method: "POST",
          body: JSON.stringify({ phone, password }),
        });
        if (passwordElement) {
          passwordElement.value = "";
        }
        const saved = Array.isArray(data.saved) && data.saved.length > 0 ? data.saved.join("、") : "运行时";
        setOopzLoginStatus(formatOopzCredentialSummary(data.credentials), "success");
        AdminShell.showMessage("msg", "OOPZ 凭据已保存到 " + saved + "，建议重启后完整生效");
        setPageState("OOPZ 登录成功", "success");
        await loadConfig();
      } catch (error) {
        setOopzLoginStatus(error.message || "OOPZ 登录失败", "error");
        AdminShell.showMessage("msg", error.message || "OOPZ 登录失败", true);
        setPageState("OOPZ 登录失败", "error");
      } finally {
        setOopzLoginButtonLoading(false);
      }
    }

    // 配置字段声明表：loadConfig 与 build 共用同一份定义，避免两侧手写映射漂移。
    // 普通字段在此声明；密钥、关键词回复、撤回排除命令等特殊字段单独处理。
    function _cfgGet(obj, path) {
      return path.split(".").reduce(function (acc, key) {
        return acc == null ? undefined : acc[key];
      }, obj);
    }

    function _cfgSet(obj, path, value) {
      const keys = path.split(".");
      let cur = obj;
      for (let i = 0; i < keys.length - 1; i++) {
        if (typeof cur[keys[i]] !== "object" || cur[keys[i]] === null) {
          cur[keys[i]] = {};
        }
        cur = cur[keys[i]];
      }
      cur[keys[keys.length - 1]] = value;
    }

    // 字段类型与默认值由后端 /admin/api/config 的 schema 下发（单一来源），
    // 这里只保留「DOM id ↔ 配置路径」绑定及少量纯前端展示标记：
    //   nullish:             加载时用 ?? 取默认（保留 0 等有意义的假值），否则用 ||。
    //   buildDefault:        保存时输入为空/0 则回退到后端默认（仅个别字段需要）。
    //   placeholderFromDefault: 用后端默认值作为输入占位提示。
    let CONFIG_SCHEMA = {};

    function _schemaMeta(path) {
      const parts = path.split(".");
      const group = CONFIG_SCHEMA[parts[0]];
      return (group && group[parts[1]]) || {};
    }

    // 后端类型 → 前端控件类型：str/str_list/json_dict 统一按 text 控件处理，
    // 其余 int/float/bool 原样透传。
    function _fieldType(field) {
      const t = _schemaMeta(field.path).type;
      return (t === "int" || t === "float" || t === "bool") ? t : "text";
    }

    function _fieldDefault(field) {
      const d = _schemaMeta(field.path).default;
      return d === undefined ? "" : d;
    }

    const CONFIG_FIELDS = [
      { id: "cfg_web_url", path: "web_player.url" },
      { id: "cfg_web_host", path: "web_player.host", buildDefault: true, placeholderFromDefault: true },
      { id: "cfg_web_port", path: "web_player.port", buildDefault: true, placeholderFromDefault: true },
      { id: "cfg_web_token_ttl", path: "web_player.token_ttl_seconds", nullish: true },
      { id: "cfg_web_cookie_age", path: "web_player.cookie_max_age_seconds", nullish: true },
      { id: "cfg_link_idle", path: "web_player.link_idle_release_seconds", nullish: true },
      { id: "cfg_send_web_link", path: "web_player.send_link_enabled" },
      { id: "cfg_cookie_secure", path: "web_player.cookie_secure" },
      { id: "cfg_admin_session_ttl", path: "web_player.admin_session_ttl_seconds", nullish: true },
      { id: "cfg_admin_cookie_secure", path: "web_player.admin_cookie_secure" },

      { id: "cfg_auto_recall_enabled", path: "auto_recall.enabled" },
      { id: "cfg_auto_recall_delay", path: "auto_recall.delay" },

      { id: "cfg_area_notify_enabled", path: "area_join_notify.enabled" },
      { id: "cfg_area_poll", path: "area_join_notify.poll_interval_seconds" },
      { id: "cfg_area_auto_role_id", path: "area_join_notify.auto_assign_role_id" },
      { id: "cfg_area_auto_role_name", path: "area_join_notify.auto_assign_role_name" },
      { id: "cfg_notify_join_tpl", path: "area_join_notify.message_template" },
      { id: "cfg_notify_leave_tpl", path: "area_join_notify.message_template_leave" },

      { id: "cfg_chat_enabled", path: "chat.enabled" },


      { id: "cfg_oopz_default_area", path: "oopz.default_area" },
      { id: "cfg_oopz_default_channel", path: "oopz.default_channel" },
      { id: "cfg_oopz_login_phone", path: "oopz.login_phone" },
      { id: "cfg_agora_app_id", path: "oopz.agora_app_id" },
      { id: "cfg_agora_timeout", path: "oopz.agora_init_timeout", buildDefault: true },

      { id: "cfg_screen_share_enabled", path: "screen_share.enabled" },
      { id: "cfg_screen_share_app_id", path: "screen_share.agora_app_id" },
      { id: "cfg_screen_share_link_ttl", path: "screen_share.presenter_link_ttl_seconds" },
      { id: "cfg_screen_share_session_max", path: "screen_share.session_max_seconds" },
      { id: "cfg_screen_share_token_ttl", path: "screen_share.rtc_token_ttl_seconds" },
      { id: "cfg_screen_share_quality", path: "screen_share.default_quality" },

      { id: "cfg_netease_base_url", path: "netease.base_url", placeholderFromDefault: true },
      { id: "cfg_netease_timeout", path: "netease.audio_download_timeout" },
      { id: "cfg_netease_retries", path: "netease.audio_download_retries" },
      { id: "cfg_netease_quality", path: "netease.audio_quality", buildDefault: true },

      { id: "cfg_redis_host", path: "redis.host" },
      { id: "cfg_redis_port", path: "redis.port" },
      { id: "cfg_redis_db", path: "redis.db" },
      { id: "cfg_redis_decode", path: "redis.decode_responses" },


      { id: "cfg_music_auto_play", path: "music.auto_play_enabled" },
      { id: "cfg_music_volume", path: "music.default_volume", nullish: true },

      { id: "cfg_cooldown_enabled", path: "command_cooldown.enabled" },
      { id: "cfg_cooldown_seconds", path: "command_cooldown.default_seconds", nullish: true },
      { id: "cfg_cooldown_exempt_admins", path: "command_cooldown.exempt_admins" },

      { id: "cfg_qq_music_enabled", path: "qq_music.enabled" },
      { id: "cfg_qq_music_base_url", path: "qq_music.base_url", placeholderFromDefault: true },

      { id: "cfg_bilibili_enabled", path: "bilibili_music.enabled" },

      { id: "cfg_stats_enabled", path: "message_stats.enabled" },

      { id: "cfg_scheduler_enabled", path: "scheduler.enabled" },
      { id: "cfg_scheduler_interval", path: "scheduler.check_interval_seconds", nullish: true },
      { id: "cfg_reminder_enabled", path: "reminder.enabled" },
      { id: "cfg_reminder_max_per_user", path: "reminder.max_per_user", nullish: true },
      { id: "cfg_reminder_max_delay", path: "reminder.max_delay_hours", nullish: true },
      { id: "cfg_reminder_interval", path: "reminder.check_interval_seconds", nullish: true },
    ];

    function _loadField(config, field) {
      if (_fieldType(field) === "bool") {
        setVal(field.id, _cfgGet(config, field.path));
        return;
      }
      const raw = _cfgGet(config, field.path);
      const def = _fieldDefault(field);
      setVal(field.id, field.nullish ? (raw ?? def) : (raw || def));
      if (field.placeholderFromDefault) {
        const element = AdminShell.byId(field.id);
        if (element && def !== "" && def != null) {
          element.placeholder = String(def);
        }
      }
    }

    function _buildField(updates, field) {
      const type = _fieldType(field);
      let value;
      if (type === "bool") {
        value = chk(field.id);
      } else if (type === "int") {
        value = getInt(field.id);
        if (field.buildDefault) {
          value = value || Number(_fieldDefault(field));
        }
      } else if (type === "float") {
        value = getFloat(field.id);
      } else {
        value = val(field.id);
        if (field.buildDefault) {
          value = value || _fieldDefault(field);
        }
      }
      _cfgSet(updates, field.path, value);
    }

    async function loadConfig() {
      const data = await AdminShell.req("/admin/api/config");
      const config = data.config || {};
      const runtime = data.runtime || {};
      CONFIG_SCHEMA = data.schema || CONFIG_SCHEMA;

      CONFIG_FIELDS.forEach(function (field) {
        _loadField(config, field);
      });
      AdminShell.refreshCustomSelect("cfg_screen_share_quality");

      // 特殊字段：关键词回复用键值编辑器渲染，代理拆成开关组。
      window._kwRender(config.chat?.keyword_replies || {});
      _loadProxy(config);

      // 密钥字段：仅展示是否已配置，不回填明文（Cookie 类回填便于复用）。
      setSecretState("cfg_admin_password", config.web_player?.admin_password_configured);
      setSecretState("cfg_oopz_login_password", config.oopz?.login_password_configured);
      setSecretValue("cfg_netease_cookie", config.netease?.cookie || "", config.netease?.cookie_configured);
      setSecretState("cfg_redis_password", config.redis?.password_configured);
      setSecretState("cfg_screen_share_certificate", config.screen_share?.agora_app_certificate_configured);
      setSecretValue("cfg_qq_music_cookie", config.qq_music?.cookie || "", config.qq_music?.cookie_configured);
      setSecretValue("cfg_bilibili_cookie", config.bilibili_music?.cookie || "", config.bilibili_music?.cookie_configured);
      neteaseQr.setSaveEnabled(false);
      bilibiliQr.setSaveEnabled(false);
      renderMusicAreaHint(runtime.music_area || {});
      await loadNeteaseAccountStatus(!!config.netease?.cookie_configured);
      await loadBilibiliAccountStatus(!!config.bilibili_music?.cookie_configured);

      setPageState("配置已同步", "success");
    }

    function build() {
      const updates = {};
      CONFIG_FIELDS.forEach(function (field) {
        _buildField(updates, field);
      });

      // 特殊字段：关键词回复为键值对，OOPZ 登录密码始终随表单提交
      // （不走「留空不修改」逻辑）。
      _cfgSet(updates, "chat.keyword_replies", window._kwCollect());
      _cfgSet(updates, "oopz.login_password", val("cfg_oopz_login_password"));
      _cfgSet(updates, "oopz.proxy", _buildProxyValue());

      const adminPassword = val("cfg_admin_password");
      const neteaseCookie = val("cfg_netease_cookie");
      const redisPassword = val("cfg_redis_password");
      const qqMusicCookie = val("cfg_qq_music_cookie");
      const bilibiliCookie = val("cfg_bilibili_cookie");
      const screenShareCertificate = val("cfg_screen_share_certificate");

      if (adminPassword) {
        updates.web_player.admin_password = adminPassword;
      }
      if (neteaseCookie) {
        updates.netease.cookie = neteaseCookie;
      }
      if (redisPassword) {
        updates.redis.password = redisPassword;
      }
      if (qqMusicCookie) {
        updates.qq_music.cookie = qqMusicCookie;
      }
      if (bilibiliCookie) {
        updates.bilibili_music.cookie = bilibiliCookie;
      }
      if (screenShareCertificate) {
        updates.screen_share.agora_app_certificate = screenShareCertificate;
      }

      return updates;
    }

    async function saveConfig(persist) {
      try {
        const data = await AdminShell.req("/admin/api/config", {
          method: "POST",
          body: JSON.stringify({ updates: build(), persist: !!persist }),
        });
        if (Array.isArray(data.errors) && data.errors.length > 0) {
          AdminShell.showMessage("msg", "部分失败：" + data.errors.join(" | "), true);
          setPageState("配置保存有错误", "error");
        } else {
          AdminShell.showMessage("msg", data.message || (data.persisted ? "配置已保存到 config.py" : "配置已应用到当前进程"));
          setPageState(data.persisted ? "配置已保存" : "配置已应用", "success");
        }
        await loadConfig();
      } catch (error) {
        AdminShell.showMessage("msg", error.message, true);
        setPageState(error.message || "配置保存失败", "error");
      }
    }

    async function resetOverrides() {
      try {
        const data = await AdminShell.req("/admin/api/config/reset", { method: "POST", body: "{}" });
        AdminShell.showMessage("msg", data.message || "已重新加载 config.py");
        setPageState("配置已重新加载", "success");
        await loadConfig();
      } catch (error) {
        AdminShell.showMessage("msg", error.message, true);
        setPageState(error.message || "恢复运行配置失败", "error");
      }
    }

    function initTabs() {
      var tabs = document.querySelectorAll(".cfg-tab");
      var panels = document.querySelectorAll(".cfg-panel");
      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
          var key = tab.dataset.tab;
          tabs.forEach(function (t) { t.classList.toggle("is-active", t.dataset.tab === key); });
          panels.forEach(function (p) { p.classList.toggle("is-active", p.dataset.panel === key); });
        });
      });
    }

    AdminShell.registerActions({
      "refresh-config": () => loadConfig(),
      "reset-overrides": () => resetOverrides(),
      "save-config": () => saveConfig(true),
      "toggle-secret": (el) => toggleSecret(el.dataset.secret, el),
      "kw-add": () => window._kwAdd(),
      "oopz-login": () => loginOopzAccount(),
      "netease-qr-refresh": () => refreshNeteaseQr(),
      "netease-qr-save": () => saveNeteaseQrCookie(true),
      "bilibili-qr-refresh": () => refreshBilibiliQr(),
      "bilibili-qr-save": () => saveBilibiliQrCookie(true),
      "proxy-mode": () => _applyProxyModeState(),
    });
    initTabs();
    AdminShell.upgradeSelect("cfg_proxy_mode");
    AdminShell.upgradeSelect("cfg_proxy_scheme");
    AdminShell.upgradeSelect("cfg_screen_share_quality");
    AdminShell.bootstrapAuth({
      page: "config",
      loggedInText: "已登录配置页",
      onLogin: () => loadConfig(),
      onLoggedOut: () => setPageState("等待操作", "warning"),
      onLoginError: () => setPageState("登录失败", "error"),
    });
