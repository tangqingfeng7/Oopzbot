    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setMicroStatus(text, variant, "schedulerState");
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    var WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"];

    function weekdaysLabel(wd) {
      if (!wd) return "-";
      var nums = String(wd).split(",").map(Number);
      if (nums.length === 7) return "每天";
      return nums.map(function (n) { return "周" + (WEEKDAY_NAMES[n] || n); }).join(", ");
    }

    function renderScheduledTable(items) {
      if (!items || !items.length) {
        AdminShell.byId("scheduledRows").innerHTML =
          '<tr><td colspan="7" class="empty-state">暂无定时消息</td></tr>';
        return;
      }
      var rows = items.map(function (t) {
        var status = t.enabled ? '<span class="micro-status is-success">启用</span>' : '<span class="micro-status is-warning">停用</span>';
        var time = String(t.cron_hour).padStart(2, "0") + ":" + String(t.cron_minute).padStart(2, "0");
        return (
          "<tr>" +
            "<td>" + t.id + "</td>" +
            '<td class="table-emphasis">' + escapeHtml(t.name) + "</td>" +
            "<td>" + time + "</td>" +
            "<td>" + weekdaysLabel(t.weekdays) + "</td>" +
            "<td>" + escapeHtml((t.message_text || "").slice(0, 40)) + "</td>" +
            "<td>" + status + "</td>" +
            '<td><button class="btn btn-sm btn-ghost" onclick="toggleScheduled(' + t.id + ')">' +
              (t.enabled ? "停用" : "启用") +
            '</button> <button class="btn btn-sm btn-danger" onclick="deleteScheduled(' + t.id + ')">删除</button></td>' +
          "</tr>"
        );
      }).join("");
      AdminShell.byId("scheduledRows").innerHTML = rows;
    }

    function renderReminderTable(items) {
      if (!items || !items.length) {
        AdminShell.byId("reminderRows").innerHTML =
          '<tr><td colspan="4" class="empty-state">暂无待执行提醒</td></tr>';
        return;
      }
      var rows = items.map(function (r) {
        return (
          "<tr>" +
            "<td>" + r.id + "</td>" +
            "<td>" + escapeHtml(r.user_id ? r.user_id.slice(0, 12) : "-") + "</td>" +
            "<td>" + escapeHtml(r.fire_at) + "</td>" +
            "<td>" + escapeHtml((r.message_text || "").slice(0, 60)) + "</td>" +
          "</tr>"
        );
      }).join("");
      AdminShell.byId("reminderRows").innerHTML = rows;
    }

    async function loadScheduler() {
      var scheduled = await AdminShell.req("/admin/api/scheduled-messages");
      renderScheduledTable(scheduled.items || []);

      var reminders = await AdminShell.req("/admin/api/reminders");
      renderReminderTable(reminders.items || []);

      setPageState("列表已同步", "success");
    }

    async function createScheduled() {
      var name = (AdminShell.byId("schName").value || "").trim();
      var hour = parseInt(AdminShell.byId("schHour").value || "0", 10);
      var minute = parseInt(AdminShell.byId("schMinute").value || "0", 10);
      var weekdays = (AdminShell.byId("schWeekdays").value || "0,1,2,3,4,5,6").trim();
      var channel_id = (AdminShell.byId("schChannel").value || "").trim();
      var area_id = (AdminShell.byId("schArea").value || "").trim();
      var message_text = (AdminShell.byId("schText").value || "").trim();

      if (!name || !channel_id || !area_id || !message_text) {
        AdminShell.showMessage("createMsg", "请填写所有必填项", true);
        return;
      }

      try {
        await AdminShell.req("/admin/api/scheduled-messages", {
          method: "POST",
          body: JSON.stringify({
            name: name,
            cron_hour: hour,
            cron_minute: minute,
            weekdays: weekdays,
            channel_id: channel_id,
            area_id: area_id,
            message_text: message_text,
          }),
        });
        AdminShell.showMessage("createMsg", "创建成功");
        AdminShell.byId("schName").value = "";
        AdminShell.byId("schText").value = "";
        await loadScheduler();
      } catch (error) {
        AdminShell.showMessage("createMsg", error.message, true);
      }
    }

    async function toggleScheduled(id) {
      try {
        await AdminShell.req("/admin/api/scheduled-messages/" + id + "/toggle", {
          method: "POST",
          body: "{}",
        });
        await loadScheduler();
      } catch (error) {
        setPageState("操作失败: " + error.message, "error");
      }
    }

    async function deleteScheduled(id) {
      try {
        await AdminShell.req("/admin/api/scheduled-messages/" + id, {
          method: "DELETE",
        });
        await loadScheduler();
      } catch (error) {
        setPageState("删除失败: " + error.message, "error");
      }
    }

    async function check() {
      try {
        await AdminShell.req("/admin/api/me");
        AdminShell.setAuthState({
          loggedIn: true,
          loggedInText: "已登录定时任务",
          statusTargets: ["topStatus", "mobileStatus"],
        });
        await loadScheduler();
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

    AdminShell.init({ page: "scheduler", passwordHandler: login });
    check();
