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

    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setStatus(text, variant, "railState");
    }

    function setSecretState(id, configured) {
      const element = AdminShell.byId(id);
      if (!element) {
        return;
      }
      element.type = "password";
      element.value = "";
      element.placeholder = configured ? "已配置，留空表示不修改" : "未配置";
      const button = element.parentElement && element.parentElement.querySelector("button");
      if (button) {
        button.textContent = "显示";
      }
    }

    function setSecretValue(id, value, configured) {
      const element = AdminShell.byId(id);
      if (!element) {
        return;
      }
      element.type = "password";
      element.value = value || "";
      element.placeholder = configured && !value ? "已配置，留空表示不修改" : "";
      const button = element.parentElement && element.parentElement.querySelector("button");
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

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录配置页",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadConfig();
      } catch (_) {
        AdminShell.setAuthState({
          loggedIn: false,
          loggedOutText: "等待登录",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        AdminShell.showMessage("loginMsg", "");
        setPageState("等待操作", "warning");
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

    async function loadConfig() {
      const data = await AdminShell.req("/admin/api/config");
      const config = data.config || {};

      setVal("cfg_web_url", config.web_player?.url || "");
      setVal("cfg_web_token_ttl", config.web_player?.token_ttl_seconds || 0);
      setVal("cfg_web_cookie_age", config.web_player?.cookie_max_age_seconds || 0);
      setVal("cfg_link_idle", config.web_player?.link_idle_release_seconds || 0);
      setVal("cfg_cookie_secure", config.web_player?.cookie_secure);
      setVal("cfg_admin_session_ttl", config.web_player?.admin_session_ttl_seconds || 0);
      setVal("cfg_admin_cookie_secure", config.web_player?.admin_cookie_secure);

      setVal("cfg_auto_recall_enabled", config.auto_recall?.enabled);
      setVal("cfg_auto_recall_delay", config.auto_recall?.delay || 30);
      setVal("cfg_area_notify_enabled", config.area_join_notify?.enabled);
      setVal("cfg_area_poll", config.area_join_notify?.poll_interval_seconds || 2);
      setVal("cfg_chat_enabled", config.chat?.enabled);
      setVal("cfg_profanity_enabled", config.profanity?.enabled);
      setVal("cfg_mute_duration", config.profanity?.mute_duration || 5);
      setVal("cfg_warn_before_mute", config.profanity?.warn_before_mute);
      setVal("cfg_skip_admins", config.profanity?.skip_admins);
      setVal("cfg_context_detection", config.profanity?.context_detection);
      setVal("cfg_context_window", config.profanity?.context_window || 30);
      setVal("cfg_context_max_messages", config.profanity?.context_max_messages || 10);
      setVal("cfg_ai_detection", config.profanity?.ai_detection);
      setVal("cfg_ai_min_length", config.profanity?.ai_min_length || 2);

      setVal("cfg_oopz_default_area", config.oopz?.default_area || "");
      setVal("cfg_oopz_default_channel", config.oopz?.default_channel || "");
      setVal("cfg_oopz_proxy", config.oopz?.proxy || "");
      setVal("cfg_oopz_announcement", config.oopz?.use_announcement_style);

      setVal("cfg_netease_base_url", config.netease?.base_url || "");
      setVal("cfg_netease_timeout", config.netease?.audio_download_timeout || 120);
      setVal("cfg_netease_retries", config.netease?.audio_download_retries || 2);
      setVal("cfg_netease_quality", config.netease?.audio_quality || "standard");

      setVal("cfg_redis_host", config.redis?.host || "");
      setVal("cfg_redis_port", config.redis?.port || 6379);
      setVal("cfg_redis_db", config.redis?.db || 0);
      setVal("cfg_redis_decode", config.redis?.decode_responses);

      setVal("cfg_doubao_enabled", config.doubao_chat?.enabled);
      setVal("cfg_doubao_base_url", config.doubao_chat?.base_url || "");
      setVal("cfg_doubao_model", config.doubao_chat?.model || "");
      setVal("cfg_doubao_max_tokens", config.doubao_chat?.max_tokens || 256);
      setVal("cfg_doubao_temperature", config.doubao_chat?.temperature ?? 0.7);
      setVal("cfg_doubao_system_prompt", config.doubao_chat?.system_prompt || "");

      setVal("cfg_doubao_img_enabled", config.doubao_image?.enabled);
      setVal("cfg_doubao_img_base_url", config.doubao_image?.base_url || "");
      setVal("cfg_doubao_img_model", config.doubao_image?.model || "");
      setVal("cfg_doubao_img_size", config.doubao_image?.size || "");
      setVal("cfg_doubao_img_watermark", config.doubao_image?.watermark);

      setSecretState("cfg_admin_password", config.web_player?.admin_password_configured);
      setSecretValue("cfg_netease_cookie", config.netease?.cookie || "", config.netease?.cookie_configured);
      setSecretState("cfg_redis_password", config.redis?.password_configured);
      setSecretValue("cfg_doubao_api_key", config.doubao_chat?.api_key || "", config.doubao_chat?.api_key_configured);
      setSecretValue("cfg_doubao_img_api_key", config.doubao_image?.api_key || "", config.doubao_image?.api_key_configured);

      setPageState("配置已同步", "success");
    }

    function build() {
      const updates = {
        web_player: {
          url: val("cfg_web_url"),
          token_ttl_seconds: getInt("cfg_web_token_ttl"),
          cookie_max_age_seconds: getInt("cfg_web_cookie_age"),
          link_idle_release_seconds: getInt("cfg_link_idle"),
          cookie_secure: chk("cfg_cookie_secure"),
          admin_session_ttl_seconds: getInt("cfg_admin_session_ttl"),
          admin_cookie_secure: chk("cfg_admin_cookie_secure"),
        },
        auto_recall: {
          enabled: chk("cfg_auto_recall_enabled"),
          delay: getInt("cfg_auto_recall_delay"),
        },
        area_join_notify: {
          enabled: chk("cfg_area_notify_enabled"),
          poll_interval_seconds: getInt("cfg_area_poll"),
        },
        chat: {
          enabled: chk("cfg_chat_enabled"),
        },
        profanity: {
          enabled: chk("cfg_profanity_enabled"),
          mute_duration: getInt("cfg_mute_duration"),
          warn_before_mute: chk("cfg_warn_before_mute"),
          skip_admins: chk("cfg_skip_admins"),
          context_detection: chk("cfg_context_detection"),
          context_window: getInt("cfg_context_window"),
          context_max_messages: getInt("cfg_context_max_messages"),
          ai_detection: chk("cfg_ai_detection"),
          ai_min_length: getInt("cfg_ai_min_length"),
        },
        oopz: {
          default_area: val("cfg_oopz_default_area"),
          default_channel: val("cfg_oopz_default_channel"),
          proxy: val("cfg_oopz_proxy"),
          use_announcement_style: chk("cfg_oopz_announcement"),
        },
        netease: {
          base_url: val("cfg_netease_base_url"),
          audio_download_timeout: getInt("cfg_netease_timeout"),
          audio_download_retries: getInt("cfg_netease_retries"),
          audio_quality: val("cfg_netease_quality") || "standard",
        },
        redis: {
          host: val("cfg_redis_host"),
          port: getInt("cfg_redis_port"),
          db: getInt("cfg_redis_db"),
          decode_responses: chk("cfg_redis_decode"),
        },
        doubao_chat: {
          enabled: chk("cfg_doubao_enabled"),
          base_url: val("cfg_doubao_base_url"),
          model: val("cfg_doubao_model"),
          max_tokens: getInt("cfg_doubao_max_tokens"),
          temperature: getFloat("cfg_doubao_temperature"),
          system_prompt: val("cfg_doubao_system_prompt"),
        },
        doubao_image: {
          enabled: chk("cfg_doubao_img_enabled"),
          base_url: val("cfg_doubao_img_base_url"),
          model: val("cfg_doubao_img_model"),
          size: val("cfg_doubao_img_size"),
          watermark: chk("cfg_doubao_img_watermark"),
        },
      };

      const adminPassword = val("cfg_admin_password");
      const neteaseCookie = val("cfg_netease_cookie");
      const redisPassword = val("cfg_redis_password");
      const doubaoApiKey = val("cfg_doubao_api_key");
      const doubaoImageApiKey = val("cfg_doubao_img_api_key");

      if (adminPassword) {
        updates.web_player.admin_password = adminPassword;
      }
      if (neteaseCookie) {
        updates.netease.cookie = neteaseCookie;
      }
      if (redisPassword) {
        updates.redis.password = redisPassword;
      }
      if (doubaoApiKey) {
        updates.doubao_chat.api_key = doubaoApiKey;
      }
      if (doubaoImageApiKey) {
        updates.doubao_image.api_key = doubaoImageApiKey;
      }

      return updates;
    }

    async function saveConfig(persist) {
      try {
        const data = await AdminShell.req("/admin/api/config", {
          method: "POST",
          body: JSON.stringify({ updates: build(), persist }),
        });
        if (Array.isArray(data.errors) && data.errors.length > 0) {
          AdminShell.showMessage("msg", "部分失败：" + data.errors.join(" | "), true);
          setPageState("配置保存有错误", "error");
        } else {
          AdminShell.showMessage("msg", persist ? "配置已保存并持久化" : "配置已更新，仅当前进程生效");
          setPageState("配置已保存", "success");
        }
        await loadConfig();
      } catch (error) {
        AdminShell.showMessage("msg", error.message, true);
        setPageState("配置保存失败", "error");
      }
    }

    async function resetOverrides() {
      try {
        await AdminShell.req("/admin/api/config/reset", { method: "POST", body: "{}" });
        AdminShell.showMessage("msg", "已清除持久化覆盖，重启后回退到 config.py");
        setPageState("覆盖已清除", "warning");
        await loadConfig();
      } catch (error) {
        AdminShell.showMessage("msg", error.message, true);
      }
    }

    AdminShell.init({ page: "config", passwordHandler: login });
    check();
