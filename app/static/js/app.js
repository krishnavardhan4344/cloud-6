/* CloudStore front-end logic (no external libraries). */
(function () {
  "use strict";

  var $ = function (selector, root) { return (root || document).querySelector(selector); };

  function csrfToken() {
    var meta = $('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  /* ------------------------------------------------------------ helpers */
  function toast(message, type, timeout) {
    var box = $("#toasts");
    if (!box) { return; }
    var el = document.createElement("div");
    el.className = "toast toast-" + (type || "info");
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.textContent = message; // textContent => no HTML injection
    box.appendChild(el);
    window.setTimeout(function () { el.remove(); }, timeout || 5500);
  }

  function formatSize(bytes) {
    var units = ["B", "KB", "MB", "GB", "TB"];
    var size = Number(bytes) || 0;
    var i = 0;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return (i === 0 ? String(Math.round(size)) : size.toFixed(1)) + " " + units[i];
  }

  function formatDate(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return iso || ""; }
    return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  function extensionOf(name) {
    var idx = name.lastIndexOf(".");
    if (idx <= 0 || idx === name.length - 1) { return "FILE"; }
    return name.slice(idx + 1, idx + 5).toUpperCase();
  }

  /* ----------------------------------------------- shared page behaviour */
  function initCommon() {
    var toggle = $("[data-nav-toggle]");
    var nav = $("#site-nav");
    if (toggle && nav) {
      toggle.addEventListener("click", function () {
        var open = nav.classList.toggle("open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    document.addEventListener("click", function (e) {
      var close = e.target.closest(".flash-close");
      if (close) { close.parentElement.remove(); }
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-toggle-password]"), function (btn) {
      btn.addEventListener("click", function () {
        var input = document.getElementById(btn.getAttribute("data-toggle-password"));
        if (!input) { return; }
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.textContent = show ? "Hide" : "Show";
      });
    });

    // Friendly client-side validation for the registration form (server re-validates).
    var reg = $('form[data-validate="register"]');
    if (reg) {
      reg.addEventListener("submit", function (e) {
        var problems = [];
        var pw = reg.elements.password.value;
        if (!/^[A-Za-z0-9_]{3,30}$/.test(reg.elements.username.value.trim())) {
          problems.push("Username must be 3-30 characters: letters, numbers and underscores only.");
        }
        if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) {
          problems.push("Password needs at least 8 characters, including a letter and a number.");
        }
        if (pw !== reg.elements.confirm_password.value) { problems.push("Passwords do not match."); }
        if (problems.length) {
          e.preventDefault();
          toast(problems[0], "error");
        }
      });
    }
  }

  /* ------------------------------------------------------------ dashboard */
  function initDashboard() {
    var root = $("#dashboard");
    if (!root) { return; }

    var maxFileBytes = Number(root.getAttribute("data-max-file-bytes")) || 0;
    var maxFiles = Number(root.getAttribute("data-max-files")) || 20;
    var body = $("#file-body");
    var table = $("#file-table");
    var emptyState = $("#empty-state");
    var noResults = $("#no-results");
    var dropzone = $("#dropzone");
    var input = $("#file-input");
    var progressBox = $("#upload-progress");
    var progressFill = $("#upload-fill");
    var progressPct = $("#upload-percent");
    var progressLabel = $("#upload-label");
    var dialog = $("#confirm-dialog");
    var search = $("#search");
    var sortSelect = $("#sort");

    var state = { files: [], usage: null, query: "", sort: "date-desc", uploading: false };

    try {
      var initial = JSON.parse($("#initial-data").textContent);
      state.files = initial.files || [];
      state.usage = initial.usage || null;
    } catch (err) { /* will load from the API below */ }

    /* ---- API wrapper with consistent error handling ---- */
    function api(url, options) {
      options = options || {};
      options.credentials = "same-origin";
      options.headers = Object.assign({ "X-CSRF-Token": csrfToken(), "Accept": "application/json" }, options.headers || {});
      return fetch(url, options).then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          if (res.status === 401) {
            window.location.href = "/login";
            throw new Error("Your session has expired. Please sign in again.");
          }
          if (!res.ok) { throw new Error((data && data.error) || "Request failed (" + res.status + ")."); }
          return data;
        });
      }, function () {
        throw new Error("Network error. Check your connection and try again.");
      });
    }

    /* ---- rendering ---- */
    function renderUsage() {
      var u = state.usage;
      if (!u) { return; }
      $("#usage-used").textContent = u.used_human;
      $("#usage-quota").textContent = u.quota_human;
      $("#usage-count").textContent = u.count;
      var fill = $("#usage-fill");
      fill.style.width = u.percent + "%";
      fill.classList.toggle("warn", u.percent >= 75 && u.percent < 95);
      fill.classList.toggle("full", u.percent >= 95);
      $("#usage-meter").setAttribute("aria-valuenow", String(Math.round(u.percent)));
    }

    function visibleFiles() {
      var q = state.query.trim().toLowerCase();
      var list = state.files.filter(function (f) { return !q || f.name.toLowerCase().indexOf(q) !== -1; });
      var parts = state.sort.split("-");
      var key = parts[0];
      var dir = parts[1] === "asc" ? 1 : -1;
      list.sort(function (a, b) {
        var cmp;
        if (key === "name") { cmp = a.name.localeCompare(b.name, undefined, { sensitivity: "base" }); }
        else if (key === "size") { cmp = a.size - b.size; }
        else { cmp = a.uploaded_at < b.uploaded_at ? -1 : a.uploaded_at > b.uploaded_at ? 1 : a.id - b.id; }
        return cmp * dir;
      });
      return list;
    }

    function cell(label, className) {
      var td = document.createElement("td");
      if (label) { td.setAttribute("data-label", label); }
      if (className) { td.className = className; }
      return td;
    }

    function renderList() {
      var list = visibleFiles();
      body.textContent = "";
      list.forEach(function (f) {
        var tr = document.createElement("tr");

        var nameTd = cell(null, "cell-name");
        var wrap = document.createElement("div");
        wrap.className = "file-name";
        var badge = document.createElement("span");
        badge.className = "ext-badge";
        badge.textContent = extensionOf(f.name);
        var title = document.createElement("span");
        title.className = "file-title";
        title.textContent = f.name;
        wrap.appendChild(badge);
        wrap.appendChild(title);
        nameTd.appendChild(wrap);

        var sizeTd = cell("Size");
        sizeTd.textContent = f.size_human || formatSize(f.size);

        var dateTd = cell("Uploaded");
        dateTd.textContent = formatDate(f.uploaded_at);

        var actTd = cell(null, "col-actions");
        var actions = document.createElement("div");
        actions.className = "actions";
        var dl = document.createElement("a");
        dl.className = "btn btn-sm";
        dl.href = f.download_url;
        dl.textContent = "Download";
        dl.setAttribute("aria-label", "Download " + f.name);
        var del = document.createElement("button");
        del.type = "button";
        del.className = "btn btn-sm btn-danger";
        del.textContent = "Delete";
        del.setAttribute("aria-label", "Delete " + f.name);
        del.addEventListener("click", function () { confirmDelete(f); });
        actions.appendChild(dl);
        actions.appendChild(del);
        actTd.appendChild(actions);

        tr.appendChild(nameTd);
        tr.appendChild(sizeTd);
        tr.appendChild(dateTd);
        tr.appendChild(actTd);
        body.appendChild(tr);
      });

      var hasFiles = state.files.length > 0;
      table.hidden = list.length === 0;
      emptyState.hidden = hasFiles;
      noResults.hidden = !hasFiles || list.length > 0;
    }

    function render() { renderUsage(); renderList(); }

    function refresh() {
      return api("/api/files").then(function (data) {
        state.files = data.files;
        state.usage = data.usage;
        render();
      }).catch(function (err) { toast(err.message, "error"); });
    }

    /* ---- upload ---- */
    function setProgress(fraction, label) {
      var pct = Math.round(fraction * 100);
      progressFill.style.width = pct + "%";
      progressPct.textContent = pct + "%";
      if (label) { progressLabel.textContent = label; }
    }

    function finishUpload() {
      state.uploading = false;
      dropzone.classList.remove("busy");
      input.value = "";
      window.setTimeout(function () { progressBox.hidden = true; setProgress(0); }, 700);
    }

    function uploadFiles(fileList) {
      if (state.uploading) { toast("Please wait for the current upload to finish.", "info"); return; }
      var files = Array.prototype.slice.call(fileList);
      if (!files.length) { return; }
      if (files.length > maxFiles) {
        toast("You can upload at most " + maxFiles + " files at a time.", "error");
        return;
      }

      var accepted = files.filter(function (f) {
        if (maxFileBytes && f.size > maxFileBytes) {
          toast("'" + f.name + "' is larger than " + formatSize(maxFileBytes) + " and was skipped.", "error");
          return false;
        }
        if (f.size === 0) {
          toast("'" + f.name + "' is empty and was skipped.", "error");
          return false;
        }
        return true;
      });
      if (!accepted.length) { input.value = ""; return; }

      var form = new FormData();
      accepted.forEach(function (f) { form.append("files", f, f.name); });

      state.uploading = true;
      dropzone.classList.add("busy");
      progressBox.hidden = false;
      setProgress(0, "Uploading " + accepted.length + " file(s)…");

      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/files");
      xhr.setRequestHeader("X-CSRF-Token", csrfToken());
      xhr.setRequestHeader("Accept", "application/json");
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable) { setProgress(e.loaded / e.total); }
      };
      xhr.onload = function () {
        var data = null;
        try { data = JSON.parse(xhr.responseText); } catch (err) { /* ignore */ }
        if (xhr.status === 401) { window.location.href = "/login"; return; }
        setProgress(1, "Done");
        if (data && data.uploaded && data.uploaded.length) {
          toast(data.uploaded.length + " file(s) uploaded successfully.", "success");
        }
        if (data && data.errors) { data.errors.forEach(function (m) { toast(m, "error", 8000); }); }
        if (!data) { toast("Upload failed (" + xhr.status + ").", "error"); }
        else if (!data.uploaded && !data.errors && data.error) { toast(data.error, "error"); }
        finishUpload();
        refresh();
      };
      xhr.onerror = function () {
        toast("Upload failed. Check your connection, or the file may exceed the size limit.", "error");
        finishUpload();
      };
      xhr.onabort = function () { finishUpload(); };
      xhr.send(form);
    }

    input.addEventListener("change", function () { uploadFiles(input.files); });
    ["dragenter", "dragover"].forEach(function (name) {
      dropzone.addEventListener(name, function (e) { e.preventDefault(); dropzone.classList.add("dragover"); });
    });
    ["dragleave", "drop"].forEach(function (name) {
      dropzone.addEventListener(name, function (e) { e.preventDefault(); dropzone.classList.remove("dragover"); });
    });
    dropzone.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files) { uploadFiles(e.dataTransfer.files); }
    });
    dropzone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    // Stop the browser from opening a file that is dropped outside the drop zone.
    ["dragover", "drop"].forEach(function (name) {
      window.addEventListener(name, function (e) { if (!dropzone.contains(e.target)) { e.preventDefault(); } });
    });

    /* ---- delete ---- */
    function deleteFile(f) {
      return api("/api/files/" + f.id, { method: "DELETE" }).then(function (data) {
        toast(data.message, "success");
        state.files = state.files.filter(function (x) { return x.id !== f.id; });
        if (data.usage) { state.usage = data.usage; }
        render();
      }).catch(function (err) {
        toast(err.message, "error");
        refresh();
      });
    }

    function confirmDelete(f) {
      if (dialog && typeof dialog.showModal === "function") {
        $("#confirm-text").textContent = "“" + f.name + "” (" + f.size_human + ") will be permanently removed.";
        var onClose = function () {
          dialog.removeEventListener("close", onClose);
          if (dialog.returnValue === "confirm") { deleteFile(f); }
        };
        dialog.returnValue = "cancel";
        dialog.addEventListener("close", onClose);
        dialog.showModal();
      } else if (window.confirm("Delete '" + f.name + "' permanently?")) {
        deleteFile(f);
      }
    }

    /* ---- search / sort ---- */
    search.addEventListener("input", function () { state.query = search.value; renderList(); });
    sortSelect.addEventListener("change", function () { state.sort = sortSelect.value; renderList(); });

    render();
    if (!state.usage) { refresh(); }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCommon();
    initDashboard();
  });
})();
