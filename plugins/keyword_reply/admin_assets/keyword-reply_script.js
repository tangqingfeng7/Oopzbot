    function setPageState(text, variant) {
      AdminShell.setStatus(text, variant, "topStatus");
      AdminShell.setStatus(text, variant, "mobileStatus");
      AdminShell.setMicroStatus(text, variant, "keywordState");
    }

    function addRow(key, val) {
      var list = AdminShell.byId("kwList");
      var row = document.createElement("div");
      row.className = "kw-row";
      row.innerHTML =
        '<input class="kw-key" type="text" placeholder="关键词" value="' + AdminShell.escapeHtml(key) + '">' +
        '<input class="kw-val" type="text" placeholder="回复内容" value="' + AdminShell.escapeHtml(val) + '">' +
        '<button type="button" class="kw-del" title="删除">&times;</button>';
      row.querySelector(".kw-del").onclick = function () { row.remove(); };
      list.appendChild(row);
      return row;
    }

    function collect() {
      var obj = {};
      AdminShell.byId("kwList").querySelectorAll(".kw-row").forEach(function (row) {
        var key = row.querySelector(".kw-key").value.trim();
        var val = row.querySelector(".kw-val").value;
        if (key) obj[key] = val;
      });
      return obj;
    }

    async function loadKeywords() {
      var data = await AdminShell.req("/admin/api/keyword-replies");
      AdminShell.byId("kwList").innerHTML = "";
      Object.entries(data.keyword_replies || {}).forEach(function (pair) { addRow(pair[0], pair[1]); });
      setPageState("已同步", "success");
    }

    async function saveKeywords() {
      try {
        var result = await AdminShell.req("/admin/api/plugins/keyword_reply/config", {
          method: "POST",
          body: JSON.stringify({ config: { keyword_replies: collect() } }),
        });
        await loadKeywords();
        setPageState(result.reload || "已保存", "success");
      } catch (error) {
        setPageState("保存失败: " + error.message, "error");
      }
    }

    AdminShell.registerActions({
      "refresh-keywords": () => loadKeywords(),
      "save-keywords": () => saveKeywords(),
      "kw-add": () => {
        var row = addRow("", "");
        row.querySelector(".kw-key").focus();
      },
    });
    AdminShell.bootstrapAuth({
      page: "keyword-reply",
      loggedInText: "已登录关键词回复",
      loginSuccessMessage: null,
      onLogin: () => loadKeywords(),
      onLoggedOut: () => setPageState("等待同步", "warning"),
      onLoginError: () => setPageState("登录失败", "error"),
    });
