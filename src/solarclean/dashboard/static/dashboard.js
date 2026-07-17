// Dashboard behaviour. Plain fetch + polling; no build step, no framework.
// Server does the work — this file only sends requests and updates the DOM.
// Charts render stored artifact values passed through by the server; nothing
// is computed here beyond drawing.

(function () {
  "use strict";

  // --- theme toggle ---------------------------------------------------
  // The persisted theme is applied by an inline <head> script before paint;
  // this button just flips and stores it.

  var themeToggle = document.getElementById("theme-toggle");
  function updateThemeLabel() {
    var label = themeToggle && themeToggle.querySelector(".theme-label");
    if (label) label.textContent = document.documentElement.dataset.theme === "dark" ?
      "Night shift" : "Daylight";
  }
  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var root = document.documentElement;
      var next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("solarclean-theme", next); } catch (e) { /* ignore */ }
      updateThemeLabel();
      restyleCharts();
    });
    updateThemeLabel();
  }

  // --- audit mode -----------------------------------------------------
  // The source trace is an interaction layer over stored figures. It never
  // fetches or derives another value; it reveals the artifact annotations
  // already attached to the rendered element.

  var auditToggle = document.getElementById("audit-toggle");
  var auditPopover = document.getElementById("audit-popover");
  function setAuditMode(enabled) {
    document.body.classList.toggle("audit-mode", enabled);
    if (auditToggle) auditToggle.setAttribute("aria-pressed", enabled ? "true" : "false");
    if (!enabled && auditPopover) auditPopover.hidden = true;
  }
  if (auditToggle) {
    auditToggle.addEventListener("click", function () {
      setAuditMode(!document.body.classList.contains("audit-mode"));
    });
  }
  document.querySelectorAll(".footer-audit-toggle").forEach(function (button) {
    button.addEventListener("click", function () { setAuditMode(true); });
  });
  document.addEventListener("click", function (event) {
    if (!document.body.classList.contains("audit-mode") || !auditPopover) return;
    var target = event.target.closest("[data-audit-source]");
    if (!target) return;
    event.preventDefault();
    document.getElementById("audit-popover-title").textContent =
      target.dataset.auditSource || "Stored artifact";
    document.getElementById("audit-popover-detail").textContent =
      target.dataset.auditDetail || "This figure is read from the named stored artifact.";
    var check = document.getElementById("audit-popover-check");
    check.textContent = target.dataset.auditCheck || "";
    check.hidden = !target.dataset.auditCheck;
    auditPopover.hidden = false;
  });
  var auditClose = document.querySelector(".audit-close");
  if (auditClose) auditClose.addEventListener("click", function () { auditPopover.hidden = true; });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && auditPopover) auditPopover.hidden = true;
  });

  // --- run fingerprints -----------------------------------------------

  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function blendChannel(a, b, mix) { return Math.round(a + (b - a) * mix); }
  function drawRunFingerprint(canvas, payload) {
      var dates = payload.dates || [];
      var ghi = payload.ghi || [];
      var cleanliness = payload.cleanliness || [];
      if (!dates.length) {
        canvas.hidden = true;
        canvas.parentElement.classList.add("fingerprint-empty");
        return;
      }
      canvas.width = dates.length;
      canvas.height = 32;
      var context = canvas.getContext("2d");
      context.imageSmoothingEnabled = false;
      var finiteGhi = ghi.filter(function (value) { return typeof value === "number" && isFinite(value); });
      var minGhi = finiteGhi.length ? Math.min.apply(null, finiteGhi) : 0;
      var maxGhi = finiteGhi.length ? Math.max.apply(null, finiteGhi) : 1;
      var cleaningDates = new Set(payload.cleaning_dates || []);
      dates.forEach(function (date, index) {
        var ghiValue = typeof ghi[index] === "number" ? ghi[index] : minGhi;
        var ghiLevel = maxGhi === minGhi ? 0.6 : clamp((ghiValue - minGhi) / (maxGhi - minGhi), 0, 1);
        var cleanValue = typeof cleanliness[index] === "number" ? cleanliness[index] : 1;
        var dustLevel = clamp((1 - cleanValue) / 0.3, 0, 1);
        var clear = [30, 80, 108];
        var dusty = [165, 109, 46];
        var light = 0.55 + ghiLevel * 0.55;
        var red = clamp(blendChannel(clear[0], dusty[0], dustLevel) * light, 0, 255);
        var green = clamp(blendChannel(clear[1], dusty[1], dustLevel) * light, 0, 255);
        var blue = clamp(blendChannel(clear[2], dusty[2], dustLevel) * light, 0, 255);
        context.fillStyle = "rgb(" + red + "," + green + "," + blue + ")";
        context.fillRect(index, 0, 1, canvas.height);
        if (cleaningDates.has(date)) {
          context.fillStyle = "#d8f2e4";
          context.fillRect(index, 0, 1, 9);
        }
      });
  }

  function loadRunFingerprint(canvas) {
    if (canvas.dataset.fingerprintState) return;
    canvas.dataset.fingerprintState = "loading";
    if (canvas.dataset.fingerprintSource) {
      var source = document.getElementById(canvas.dataset.fingerprintSource);
      try {
        drawRunFingerprint(canvas, JSON.parse(source && source.dataset.fingerprint || "{}"));
      } catch (error) {
        drawRunFingerprint(canvas, {});
      }
      canvas.dataset.fingerprintState = "ready";
      return;
    }
    if (canvas.dataset.fingerprint) {
      try { drawRunFingerprint(canvas, JSON.parse(canvas.dataset.fingerprint)); }
      catch (error) { drawRunFingerprint(canvas, {}); }
      canvas.dataset.fingerprintState = "ready";
      return;
    }
    fetch(canvas.dataset.fingerprintUrl)
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) { drawRunFingerprint(canvas, payload); })
      .catch(function () { drawRunFingerprint(canvas, {}); })
      .finally(function () { canvas.dataset.fingerprintState = "ready"; });
  }

  function initRunFingerprints(root) {
    var scope = root || document;
    var canvases = Array.from(scope.querySelectorAll("canvas.run-fingerprint"))
      .filter(function (canvas) { return !canvas.dataset.fingerprintBound; });
    canvases.forEach(function (canvas) { canvas.dataset.fingerprintBound = "true"; });
    var lazy = canvases.filter(function (canvas) { return canvas.dataset.fingerprintUrl; });
    canvases.filter(function (canvas) { return !canvas.dataset.fingerprintUrl; })
      .forEach(loadRunFingerprint);
    if (!("IntersectionObserver" in window)) {
      lazy.forEach(loadRunFingerprint);
      return;
    }
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        loadRunFingerprint(entry.target);
      });
    }, { rootMargin: "160px 0px" });
    lazy.forEach(function (canvas) { observer.observe(canvas); });
  }
  window.initRunFingerprints = initRunFingerprints;
  initRunFingerprints(document);

  var kindSelect = document.getElementById("kind");
  if (kindSelect) {
    var analysisDescriptions = {
      "compare": "Compare baseline, reactive cleaning, and coating under identical weather and events.",
      "monte-carlo": "Repeat the comparison across controlled random seeds to measure uncertainty and winner probability.",
      "sensitivity-oneway": "Change one assumption at a time to see which inputs influence the result most.",
      "winner-map": "Vary two assumptions together and map which strategy wins across the grid.",
      "break-even": "Find the parameter value where two selected strategies have equal net benefit."
    };
    var showOptionsForKind = function () {
      document.querySelectorAll(".kind-opts").forEach(function (row) {
        row.hidden = row.dataset.kind !== kindSelect.value;
      });
      var summary = document.getElementById("analysis-summary");
      if (summary) summary.textContent = analysisDescriptions[kindSelect.value] || "";
    };
    kindSelect.addEventListener("change", showOptionsForKind);
    showOptionsForKind();
  }

  var configSelect = document.getElementById("config");
  var configLink = document.getElementById("config-link");
  if (configSelect && configLink) {
    var updateSimulationPeriod = function () {
      var option = configSelect.selectedOptions[0];
      if (!option) return;
      var startInput = document.getElementById("start-date");
      var endInput = document.getElementById("end-date");
      var note = document.getElementById("period-note");
      if (startInput) startInput.value = option.dataset.start || "";
      if (endInput) endInput.value = option.dataset.end || "";
      if (note) {
        note.textContent = "Whole days in " + (option.dataset.timezone || "the site timezone") +
          "; this run-only override does not edit the YAML.";
      }
    };
    var updateParameterCatalog = function (parameters) {
      ["parameters", "parameter-a", "parameter-b", "be-parameter"].forEach(function (id) {
        var select = document.getElementById(id);
        if (!select) return;
        var chosen = new Set(Array.from(select.selectedOptions).map(function (option) {
          return option.value;
        }));
        select.replaceChildren();
        parameters.forEach(function (parameter, index) {
          var option = document.createElement("option");
          option.value = parameter.name;
          option.textContent = parameter.name + " (" + parameter.unit + ")";
          option.title = "registry range " + parameter.low + " – " + parameter.central +
            " – " + parameter.high + " " + parameter.unit;
          option.selected = chosen.has(parameter.name) ||
            (id === "parameter-b" && chosen.size === 0 && index === 1);
          select.appendChild(option);
        });
      });
    };
    var updateConfigLink = function () {
      configLink.href = "/config/" + encodeURIComponent(configSelect.value);
    };
    configSelect.addEventListener("change", function () {
      updateConfigLink();
      updateSimulationPeriod();
      fetch("/api/configs/" + encodeURIComponent(configSelect.value) + "/parameters")
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then(updateParameterCatalog)
        .catch(function () { /* launch endpoint will report the registry error */ });
    });
    updateConfigLink();
    updateSimulationPeriod();
  }

  // --- launching runs -----------------------------------------------------

  var launchButton = document.getElementById("launch");
  if (launchButton) {
    launchButton.addEventListener("click", function () {
      var errorEl = document.getElementById("launch-error");
      errorEl.textContent = "";

      var body = { kind: kindSelect.value, config: configSelect.value };
      var startDate = document.getElementById("start-date").value;
      var endDate = document.getElementById("end-date").value;
      if (!startDate || !endDate) {
        errorEl.textContent = "Choose both a start date and an end date.";
        return;
      }
      if (endDate < startDate) {
        errorEl.textContent = "End date must be on or after start date.";
        return;
      }
      body.start_date = startDate;
      body.end_date = endDate;
      if (body.kind === "monte-carlo") {
        body.trials = parseInt(document.getElementById("trials").value, 10) || 25;
        var seed = document.getElementById("base-seed").value;
        if (seed !== "") body.base_seed = parseInt(seed, 10);
      } else if (body.kind === "sensitivity-oneway") {
        body.steps = parseInt(document.getElementById("steps").value, 10) || 5;
        var chosen = Array.from(document.getElementById("parameters").selectedOptions)
          .map(function (option) { return option.value; });
        if (chosen.length) body.parameters = chosen;
      } else if (body.kind === "winner-map") {
        body.parameter_a = document.getElementById("parameter-a").value.trim();
        body.parameter_b = document.getElementById("parameter-b").value.trim();
        body.grid_steps = parseInt(document.getElementById("grid-steps").value, 10) || 5;
        if (!body.parameter_a || !body.parameter_b) {
          errorEl.textContent = "Winner map needs both parameter names.";
          return;
        }
        if (body.parameter_a === body.parameter_b) {
          errorEl.textContent = "Pick two different parameters for the winner map.";
          return;
        }
      } else if (body.kind === "break-even") {
        body.parameter = document.getElementById("be-parameter").value.trim();
        body.scenario_a = document.getElementById("scenario-a").value;
        body.scenario_b = document.getElementById("scenario-b").value;
        if (!body.parameter) {
          errorEl.textContent = "Break-even needs a registry parameter name.";
          return;
        }
      }

      launchButton.disabled = true;
      fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then(function (response) {
          if (!response.ok) {
            return response.json().then(function (data) {
              throw new Error(data.detail || ("HTTP " + response.status));
            });
          }
          return response.json();
        })
        .then(function (job) {
          addJobRow(job);
          pollJob(job.job_id);
        })
        .catch(function (error) {
          errorEl.textContent = error.message;
        })
        .finally(function () {
          launchButton.disabled = false;
        });
    });
  }

  function formatSeconds(value) {
    if (value === null || value === undefined) return "–";
    var total = Math.max(0, Math.round(value));
    if (total < 90) return total + "s";
    var minutes = Math.floor(total / 60);
    var seconds = total % 60;
    return minutes + "m " + seconds + "s";
  }

  function addJobRow(job) {
    var panel = document.getElementById("jobs-panel");
    panel.hidden = false;
    var tbody = document.querySelector("#jobs-table tbody");
    var row = document.createElement("tr");
    row.dataset.job = job.job_id;
    row.innerHTML =
      '<td class="mono">' + job.created_at.slice(0, 19) + "</td>" +
      "<td>" + job.kind + "</td>" +
      '<td class="job-config mono"></td>' +
      '<td class="job-status"><span class="status status-queued">queued</span></td>' +
      '<td class="job-progress"><span class="progress-label mono">–</span></td>' +
      '<td class="job-elapsed mono">–</td>' +
      '<td class="job-eta mono">–</td>' +
      '<td class="job-result"></td>' +
      '<td class="job-actions"><button type="button" class="danger-quiet job-delete" data-job-id="' +
      job.job_id + '">Cancel &amp; remove</button></td>';
    row.querySelector(".job-config").textContent = job.config_name || "–";
    tbody.insertBefore(row, tbody.firstChild);
  }

  function updateJobRow(row, job) {
    var statusEl = row.querySelector(".job-status .status");
    statusEl.className = "status status-" + job.status;
    statusEl.textContent = job.status;
    statusEl.title = job.detail || "";

    var progressCell = row.querySelector(".job-progress");
    if (progressCell) {
      if (job.progress_percent !== null && job.progress_percent !== undefined) {
        var pct = Math.round(job.progress_percent);
        var fill = progressCell.querySelector(".progress-fill");
        var label = progressCell.querySelector(".progress-label");
        if (fill && label) {
          // Update in place so the CSS width transition can animate the fill.
          fill.style.width = pct + "%";
          label.textContent = pct + "%";
        } else {
          progressCell.innerHTML =
            '<div class="progress-track"><div class="progress-fill" style="width: ' + pct +
            '%"></div></div><span class="progress-label mono">' + pct + "%</span>";
        }
      } else {
        // No honest unit counts for this analysis kind: show no percentage.
        progressCell.innerHTML = '<span class="progress-label mono">–</span>';
      }
    }
    var elapsedCell = row.querySelector(".job-elapsed");
    if (elapsedCell) elapsedCell.textContent = formatSeconds(job.elapsed_seconds);
    var etaCell = row.querySelector(".job-eta");
    if (etaCell) {
      etaCell.textContent =
        job.eta_seconds !== null && job.eta_seconds !== undefined
          ? "~" + formatSeconds(job.eta_seconds)
          : "–";
    }
    var deleteBtn = row.querySelector(".job-delete");
    if (deleteBtn && job.status !== "queued" && job.status !== "running") {
      deleteBtn.textContent = "Delete";
    }
  }

  // The completed-runs gallery is server-rendered. When a job finishes, fetch
  // the page again and swap in the fresh first batch so the new run appears without
  // a manual reload (Jinja stays the only place that renders run rows).
  function refreshCompletedRuns() {
    return fetch("/")
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (!html) return false;
        var doc = new DOMParser().parseFromString(html, "text/html");
        var freshGallery = doc.querySelector("#runs-table");
        var currentGallery = document.querySelector("#runs-table");
        if (freshGallery && currentGallery) {
          currentGallery.replaceChildren.apply(
            currentGallery,
            Array.from(freshGallery.childNodes).map(function (node) { return node.cloneNode(true); })
          );
          var freshLoader = doc.querySelector("#run-archive-loader");
          var currentLoader = document.querySelector("#run-archive-loader");
          if (freshLoader && currentLoader) {
            currentLoader.dataset.nextPage = freshLoader.dataset.nextPage || "";
            currentLoader.dataset.totalPages = freshLoader.dataset.totalPages || "1";
            currentLoader.dataset.totalRuns = freshLoader.dataset.totalRuns || "0";
            currentLoader.hidden = freshLoader.hidden;
            var status = currentLoader.querySelector("#run-archive-status");
            if (status) status.textContent = "Scroll for older runs";
            var loadButton = currentLoader.querySelector("#load-more-runs");
            if (loadButton) loadButton.hidden = false;
          }
          selectEverything = false;
          initRunFingerprints(currentGallery);
          applyRunFilter();
          updateBulkDeleteState();
          return true;
        } else if (freshGallery && !currentGallery) {
          // First completed run ever: the empty-state panel has no table to
          // swap into, so take the one-off full reload.
          window.location.reload();
          return true;
        }
        return false;
      })
      .catch(function () { return false; });
  }

  function removeJobRow(row) {
    row.remove();
    var tbody = document.querySelector("#jobs-table tbody");
    if (tbody && tbody.children.length === 0) {
      document.getElementById("jobs-panel").hidden = true;
    }
  }

  function promoteCompletedJob(row, attemptsRemaining) {
    refreshCompletedRuns().then(function (refreshed) {
      if (refreshed) {
        removeJobRow(row);
      } else if (attemptsRemaining > 1) {
        setTimeout(function () {
          promoteCompletedJob(row, attemptsRemaining - 1);
        }, 1000);
      }
    });
  }

  function pollJob(jobId) {
    var consecutiveFailures = 0;
    var timer = setInterval(function () {
      fetch("/api/jobs/" + jobId)
        .then(function (r) {
          if (r.status === 404) { clearInterval(timer); return null; }
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (job) {
          if (!job) return;
          consecutiveFailures = 0;
          var row = document.querySelector('tr[data-job="' + jobId + '"]');
          if (!row) { clearInterval(timer); return; }
          updateJobRow(row, job);
          if (job.status === "done" && job.run_id) {
            row.querySelector(".job-result").innerHTML =
              '<a href="/run/' + job.run_id + '">' + job.run_id + "</a>";
            clearInterval(timer);
            promoteCompletedJob(row, 3);
          } else if (job.status === "failed") {
            var resultCell = row.querySelector(".job-result");
            resultCell.textContent = job.error || "failed";
            resultCell.className = "job-result error-text";
            clearInterval(timer);
          } else if (job.status === "cancelled") {
            clearInterval(timer);
          }
        })
        .catch(function () {
          consecutiveFailures += 1;
          if (consecutiveFailures >= 5) clearInterval(timer);
        });
    }, 2000);
  }

  // Resume polling for jobs that were still running when the page loaded.
  document.querySelectorAll("#jobs-table tr[data-job]").forEach(function (row) {
    var status = row.querySelector(".job-status").textContent.trim();
    if (status === "queued" || status === "running") pollJob(row.dataset.job);
  });

  // Delete / cancel a run session (event delegation so new rows work too).
  var jobsTable = document.getElementById("jobs-table");
  if (jobsTable) {
    jobsTable.addEventListener("click", function (event) {
      var button = event.target.closest(".job-delete");
      if (!button) return;
      var jobId = button.dataset.jobId;
      button.disabled = true;
      fetch("/api/jobs/" + jobId, { method: "DELETE" })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          var row = document.querySelector('tr[data-job="' + jobId + '"]');
          if (row) removeJobRow(row);
        })
        .catch(function () { button.disabled = false; });
    });
  }

  // --- deleting completed runs ---------------------------------------
  // Destructive: removes the run directory (exports included), so every path
  // goes through a confirm dialog first.

  function deleteRuns(runIds, errorEl) {
    var label = runIds.length === 1 ? "run " + runIds[0] : runIds.length + " runs";
    var ok = window.confirm(
      "Permanently delete " + label + "?\n\nThis removes the run directory under outputs/ " +
      "including all exports. Download the .zip first if you need the files."
    );
    if (!ok) return;
    errorEl.textContent = "";
    runIds.forEach(function (runId) {
      fetch("/api/runs/" + encodeURIComponent(runId), { method: "DELETE" })
        .then(function (r) {
          if (!r.ok) {
            return r.json().then(function (data) {
              throw new Error(data.detail || ("HTTP " + r.status + " deleting " + runId));
            });
          }
          var row = document.querySelector('[data-run="' + runId + '"]');
          if (row) row.remove();
          updateBulkDeleteState();
        })
        .catch(function (error) { errorEl.textContent = error.message; });
    });
  }

  var runsTable = document.getElementById("runs-table");
  var runArchiveLoader = document.getElementById("run-archive-loader");
  var archiveLoadPromise = null;
  var selectEverything = false;

  function archiveHasMore() {
    return Boolean(runArchiveLoader && runArchiveLoader.dataset.nextPage);
  }

  function setArchiveStatus(message) {
    var status = document.getElementById("run-archive-status");
    if (status) status.textContent = message;
  }

  function loadNextRunPage() {
    if (!runsTable || !archiveHasMore()) return Promise.resolve(false);
    if (archiveLoadPromise) return archiveLoadPromise;
    var page = parseInt(runArchiveLoader.dataset.nextPage, 10);
    var totalPages = parseInt(runArchiveLoader.dataset.totalPages, 10);
    var loadMoreButton = document.getElementById("load-more-runs");
    setArchiveStatus("Loading older runs…");
    if (loadMoreButton) loadMoreButton.disabled = true;
    archiveLoadPromise = fetch("/api/run-pages/" + page)
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.text();
      })
      .then(function (html) {
        var template = document.createElement("template");
        template.innerHTML = html;
        var cards = Array.from(template.content.querySelectorAll(".run-card"));
        if (selectEverything) {
          cards.forEach(function (card) {
            var checkbox = card.querySelector(".run-select");
            if (checkbox) checkbox.checked = true;
          });
        }
        runsTable.appendChild(template.content);
        initRunFingerprints(runsTable);
        runArchiveLoader.dataset.nextPage = page < totalPages ? String(page + 1) : "";
        var loadedCount = runsTable.querySelectorAll(".run-card").length;
        var totalRuns = runArchiveLoader.dataset.totalRuns;
        setArchiveStatus(
          archiveHasMore() ? "Loaded " + loadedCount + " of " + totalRuns + " runs" :
            "All " + totalRuns + " runs loaded"
        );
        if (loadMoreButton) loadMoreButton.hidden = !archiveHasMore();
        updateBulkDeleteState();
        return true;
      })
      .catch(function () {
        setArchiveStatus("Could not load older runs. Try again.");
        return false;
      })
      .finally(function () {
        archiveLoadPromise = null;
        if (loadMoreButton) loadMoreButton.disabled = false;
      });
    return archiveLoadPromise;
  }

  function loadAllRunPages() {
    if (!archiveHasMore()) return Promise.resolve(true);
    return loadNextRunPage().then(function (loaded) {
      return loaded ? loadAllRunPages() : false;
    });
  }

  function visibleRunCheckboxes() {
    return Array.from(document.querySelectorAll("#runs-table .run-card:not([hidden]) .run-select"));
  }

  function updateBulkDeleteState() {
    var checkboxes = visibleRunCheckboxes();
    var bulkButton = document.getElementById("delete-selected-runs");
    var selectedCount = checkboxes.filter(function (checkbox) { return checkbox.checked; }).length;
    if (bulkButton) bulkButton.disabled = selectedCount === 0;
    var compareButton = document.getElementById("compare-selected-runs");
    if (compareButton) compareButton.disabled = selectedCount !== 2;
    var selectAllButton = document.getElementById("select-all-runs");
    if (selectAllButton) {
      var allSelected = !archiveHasMore() && checkboxes.length > 0 &&
        selectedCount === checkboxes.length;
      selectAllButton.disabled = checkboxes.length === 0 || selectEverything;
      selectAllButton.textContent = selectEverything ? "Loading all runs…" :
        allSelected ? "Clear selection" : "Select all";
      selectAllButton.setAttribute("aria-pressed", allSelected ? "true" : "false");
    }
  }

  // Client-side archive filter. Cards are only hidden/shown — nothing is
  // fetched or recomputed; the full archive is pulled in first so a search
  // covers every stored run, not just the loaded pages.
  function applyRunFilter() {
    var textInput = document.getElementById("run-filter-text");
    var kindSelect2 = document.getElementById("run-filter-kind");
    if (!runsTable || (!textInput && !kindSelect2)) return;
    var query = ((textInput && textInput.value) || "").trim().toLowerCase();
    var kind = (kindSelect2 && kindSelect2.value) || "";
    var filterActive = Boolean(query || kind);
    if (filterActive && archiveHasMore()) {
      setArchiveStatus("Loading the full archive to search it…");
      loadAllRunPages().then(applyRunFilter);
      return;
    }
    var cards = Array.from(runsTable.querySelectorAll(".run-card"));
    var shown = 0;
    cards.forEach(function (card) {
      var matches = (!kind || card.dataset.kind === kind) &&
        (!query || card.textContent.toLowerCase().indexOf(query) !== -1);
      card.hidden = !matches;
      if (matches) {
        shown += 1;
      } else {
        // A hidden card must not stay silently selected for bulk delete.
        var checkbox = card.querySelector(".run-select");
        if (checkbox) checkbox.checked = false;
      }
    });
    var status = document.getElementById("run-filter-status");
    if (status) {
      status.textContent = filterActive
        ? (shown ? shown + " of " + cards.length + " runs match" : "No runs match this filter")
        : "";
    }
    if (runArchiveLoader) {
      runArchiveLoader.hidden = filterActive || !archiveHasMore();
    }
    updateBulkDeleteState();
  }

  if (runsTable) {
    var runsError = document.getElementById("runs-delete-error");
    runsTable.addEventListener("click", function (event) {
      var button = event.target.closest(".run-delete");
      if (button) deleteRuns([button.dataset.runId], runsError);
    });
    runsTable.addEventListener("change", function (event) {
      if (event.target.classList.contains("run-select")) {
        selectEverything = false;
        updateBulkDeleteState();
      }
    });
    var selectAllButton = document.getElementById("select-all-runs");
    selectAllButton.addEventListener("click", function () {
      var checkboxes = visibleRunCheckboxes();
      var allSelected = !archiveHasMore() && checkboxes.length > 0 &&
        checkboxes.every(function (checkbox) { return checkbox.checked; });
      if (allSelected) {
        checkboxes.forEach(function (checkbox) { checkbox.checked = false; });
        updateBulkDeleteState();
        return;
      }
      selectEverything = true;
      checkboxes.forEach(function (checkbox) { checkbox.checked = true; });
      updateBulkDeleteState();
      loadAllRunPages().then(function (loadedAll) {
        selectEverything = false;
        if (loadedAll) {
          applyRunFilter();
          visibleRunCheckboxes().forEach(function (checkbox) { checkbox.checked = true; });
        }
        updateBulkDeleteState();
      });
    });
    var runFilterText = document.getElementById("run-filter-text");
    var runFilterKind = document.getElementById("run-filter-kind");
    if (runFilterText) runFilterText.addEventListener("input", applyRunFilter);
    if (runFilterKind) runFilterKind.addEventListener("change", applyRunFilter);
    var bulkButton = document.getElementById("delete-selected-runs");
    bulkButton.addEventListener("click", function () {
      var selected = Array.from(document.querySelectorAll(".run-select:checked"))
        .map(function (box) { return box.value; });
      if (selected.length) deleteRuns(selected, runsError);
    });
    var compareButton = document.getElementById("compare-selected-runs");
    compareButton.addEventListener("click", function () {
      var selected = Array.from(document.querySelectorAll(".run-select:checked"))
        .map(function (box) { return box.value; });
      if (selected.length === 2) {
        window.location.href = "/compare-runs?a=" + encodeURIComponent(selected[0]) +
          "&b=" + encodeURIComponent(selected[1]);
      }
    });

    var loadMoreButton = document.getElementById("load-more-runs");
    if (loadMoreButton) loadMoreButton.addEventListener("click", loadNextRunPage);
    if (runArchiveLoader && archiveHasMore() && "IntersectionObserver" in window) {
      var archiveObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && archiveHasMore()) loadNextRunPage();
        });
      }, { rootMargin: "360px 0px" });
      archiveObserver.observe(runArchiveLoader);
    }
  }

  // --- re-run an analysis ----------------------------------------------

  var rerunButton = document.getElementById("rerun-btn");
  if (rerunButton) {
    rerunButton.addEventListener("click", function () {
      var statusEl = document.getElementById("rerun-status");
      rerunButton.disabled = true;
      statusEl.textContent = "Starting…";
      fetch("/api/runs/" + encodeURIComponent(rerunButton.dataset.runId) + "/rerun", {
        method: "POST",
      })
        .then(function (r) {
          if (!r.ok) {
            return r.json().then(function (data) {
              throw new Error(data.detail || ("HTTP " + r.status));
            });
          }
          window.location.href = "/"; // job appears in the sessions table
        })
        .catch(function (error) {
          statusEl.textContent = error.message;
          rerunButton.disabled = false;
        });
    });
  }

  // --- config editor ------------------------------------------------------

  var configEditor = document.getElementById("config-editor");
  if (configEditor) {
    configEditor.originalContent = configEditor.value;
    configEditor.savedContent = configEditor.value;
    // Edits only persist through "Validate and save"; navigating away with
    // unsaved changes silently discards them, so flag it and ask first.
    var updateDirtyFlag = function () {
      var dirty = document.getElementById("config-dirty");
      if (dirty) dirty.hidden = configEditor.value === configEditor.savedContent;
    };
    configEditor.addEventListener("input", updateDirtyFlag);
    window.addEventListener("beforeunload", function (event) {
      if (configEditor.value !== configEditor.savedContent) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
    configEditor.updateDirtyFlag = updateDirtyFlag;
  }

  function syncSiteLocationFromEditor(editor) {
    var lat = parseFloat(parseYamlScalar(editor.value, "latitude"));
    var lon = parseFloat(parseYamlScalar(editor.value, "longitude"));
    var latInput = document.getElementById("site-lat");
    var lonInput = document.getElementById("site-lon");
    var timezoneInput = document.getElementById("site-timezone");
    var marker = document.getElementById("site-map-marker");
    if (latInput) latInput.value = isNaN(lat) ? "" : lat;
    if (lonInput) lonInput.value = isNaN(lon) ? "" : lon;
    if (timezoneInput) timezoneInput.value = parseYamlScalar(editor.value, "timezone") || "";
    if (marker) {
      marker.hidden = isNaN(lat) || isNaN(lon);
      if (!marker.hidden) {
        marker.setAttribute("cx", lon);
        marker.setAttribute("cy", -lat);
      }
    }
    updateProviderNote(editor.value);
  }

  function validateConfig(saveAs) {
    var editor = document.getElementById("config-editor");
    var statusEl = document.getElementById("config-status");
    statusEl.className = "";
    statusEl.textContent = "Checking with the simulation config loader…";
    var payload = { content: editor.value };
    if (saveAs) payload.save_as = saveAs;
    fetch("/api/configs/" + encodeURIComponent(editor.dataset.name) + "/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json(); })
      .then(function (result) {
        if (!result.valid) {
          statusEl.className = "bad";
          statusEl.textContent = result.error;
        } else if (result.saved) {
          editor.savedContent = payload.content;
          if (editor.updateDirtyFlag) editor.updateDirtyFlag();
          statusEl.className = "ok";
          statusEl.textContent = "Valid. Saved — the next run uses this configuration.";
        } else if (result.error) {
          statusEl.className = "bad";
          statusEl.textContent = result.error;
        } else {
          statusEl.className = "ok";
          statusEl.textContent = "Valid. This would load for a run.";
        }
      })
      .catch(function (error) {
        statusEl.className = "bad";
        statusEl.textContent = String(error);
      });
  }

  var validateButton = document.getElementById("validate-btn");
  if (validateButton) {
    validateButton.addEventListener("click", function () { validateConfig(null); });
    var saveDefaultButton = document.getElementById("save-default-btn");
    if (saveDefaultButton) {
      saveDefaultButton.addEventListener("click", function () {
        validateConfig(document.getElementById("config-editor").dataset.name);
      });
    }
    var resetConfigButton = document.getElementById("reset-config-btn");
    if (resetConfigButton) {
      resetConfigButton.addEventListener("click", function () {
        var editor = document.getElementById("config-editor");
        var statusEl = document.getElementById("config-status");
        function restoreContent(content, message) {
          editor.value = content;
          editor.dispatchEvent(new Event("input", { bubbles: true }));
          syncSiteLocationFromEditor(editor);
          var locationStatus = document.getElementById("location-status");
          if (locationStatus) locationStatus.textContent = "";
          statusEl.className = "ok";
          statusEl.textContent = message;
        }
        if (editor.dataset.isDefault !== "true") {
          restoreContent(editor.originalContent, "Page-load values restored in the editor.");
          return;
        }
        resetConfigButton.disabled = true;
        statusEl.className = "";
        statusEl.textContent = "Loading the original Riyadh defaults…";
        fetch("/api/configs/" + encodeURIComponent(editor.dataset.name) + "/factory-default")
          .then(function (response) {
            return response.json().then(function (result) {
              if (!response.ok) throw new Error(result.detail || ("HTTP " + response.status));
              return result;
            });
          })
          .then(function (result) {
            restoreContent(
              result.content,
              "Original Riyadh defaults restored in the editor. " +
                "Validate and save to make them active."
            );
          })
          .catch(function (error) {
            statusEl.className = "bad";
            statusEl.textContent = error.message || String(error);
          })
          .finally(function () { resetConfigButton.disabled = false; });
      });
    }
  }

  // --- site location picker --------------------------------------------
  // The server applies coordinates, both timezone fields, and DST-correct
  // simulation offsets as one validated YAML update. Only nasa_power fetches
  // weather by location; fixture/csv weather still treats coordinates as metadata.

  function parseYamlScalar(content, key) {
    var match = content.match(new RegExp("^\\s*" + key + ":\\s*([^\\s#]+)", "m"));
    return match ? match[1].replace(/^["']|["']$/g, "") : null;
  }

  function updateProviderNote(content) {
    var warning = document.getElementById("provider-warning");
    if (!warning) return;
    var provider = parseYamlScalar(content, "provider");
    if (provider === "nasa_power") {
      warning.hidden = false;
      warning.textContent =
        "weather.provider is nasa_power: runs fetch live NASA POWER weather for these " +
        "coordinates — hourly irradiance, temperature, wind, humidity, and precipitation " +
        "all change with the location. Daily rainfall, seasonal soiling, event dates, and " +
        "cleaning use the selected timezone. Soiling/dust and cost calibration stay on " +
        "the Riyadh central-v2 assumption set.";
    } else if (provider) {
      warning.hidden = false;
      warning.textContent =
        "weather.provider is \"" + provider + "\": weather data is fixed, so the coordinates " +
        "below are recorded as metadata only and will NOT change simulation results.";
    } else {
      warning.hidden = true;
    }
  }

  window.initSiteMap = function () {
    var svg = document.getElementById("site-map");
    var land = document.getElementById("site-map-land");
    var editor = document.getElementById("config-editor");
    if (!svg || !land || !editor) return;
    if (typeof window.SOLARCLEAN_WORLD_LAND === "string") {
      land.setAttribute("d", window.SOLARCLEAN_WORLD_LAND);
    }

    var marker = document.getElementById("site-map-marker");
    var latInput = document.getElementById("site-lat");
    var lonInput = document.getElementById("site-lon");
    var timezoneInput = document.getElementById("site-timezone");
    var applyButton = document.getElementById("apply-location");
    var statusEl = document.getElementById("location-status");

    function placeMarker(lat, lon) {
      if (isNaN(lat) || isNaN(lon)) return;
      marker.setAttribute("cx", lon);
      marker.setAttribute("cy", -lat); // SVG y grows downward; viewBox is -90..90
      marker.hidden = false;
    }

    // Seed inputs and marker from the YAML currently in the editor.
    var initialLat = parseFloat(parseYamlScalar(editor.value, "latitude"));
    var initialLon = parseFloat(parseYamlScalar(editor.value, "longitude"));
    var initialTimezone = parseYamlScalar(editor.value, "timezone");
    if (!isNaN(initialLat)) latInput.value = initialLat;
    if (!isNaN(initialLon)) lonInput.value = initialLon;
    if (initialTimezone) timezoneInput.value = initialTimezone;
    placeMarker(initialLat, initialLon);
    updateProviderNote(editor.value);
    editor.addEventListener("input", function () { updateProviderNote(editor.value); });

    svg.addEventListener("click", function (event) {
      var point = new DOMPoint(event.clientX, event.clientY).matrixTransform(
        svg.getScreenCTM().inverse()
      );
      var lon = Math.min(180, Math.max(-180, point.x));
      var lat = Math.min(90, Math.max(-90, -point.y));
      latInput.value = lat.toFixed(4);
      lonInput.value = lon.toFixed(4);
      placeMarker(lat, lon);
      statusEl.textContent = "Picked " + lat.toFixed(4) + ", " + lon.toFixed(4) +
        " — its timezone will be detected automatically when you apply it.";
    });

    [latInput, lonInput].forEach(function (input) {
      input.addEventListener("input", function () {
        placeMarker(parseFloat(latInput.value), parseFloat(lonInput.value));
      });
    });

    applyButton.addEventListener("click", function () {
      var lat = parseFloat(latInput.value);
      var lon = parseFloat(lonInput.value);
      if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        statusEl.textContent = "Latitude must be -90..90 and longitude -180..180.";
        return;
      }
      applyButton.disabled = true;
      statusEl.textContent = "Detecting the timezone and calculating local UTC offsets…";
      fetch("/api/configs/" + encodeURIComponent(editor.dataset.name) + "/apply-location", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: editor.value,
          latitude: lat,
          longitude: lon,
        }),
      })
        .then(function (response) {
          return response.json().then(function (result) {
            if (!response.ok) throw new Error(JSON.stringify(result.detail || result));
            return result;
          });
        })
        .then(function (result) {
          if (!result.valid) throw new Error(result.error);
          editor.value = result.content;
          editor.dispatchEvent(new Event("input", { bubbles: true }));
          syncSiteLocationFromEditor(editor);
          statusEl.textContent = "Updated coordinates and timezone " + result.timezone +
            "; local period offsets are " + result.start.slice(-6) + " / " +
            result.end.slice(-6) + ". Validate and save to keep it.";
          var configStatus = document.getElementById("config-status");
          configStatus.className = "ok";
          configStatus.textContent = "The location/timezone update is valid but not saved yet.";
        })
        .catch(function (error) {
          statusEl.textContent = error.message || String(error);
        })
        .finally(function () { applyButton.disabled = false; });
    });
  };

  // --- selected-config cockpit ---------------------------------------

  function strategyLabelNode(strategy) {
    var label = document.createElement("span");
    label.className = "strategy-label strategy-" + strategy;
    var glyph = document.createElement("span");
    glyph.className = "strategy-glyph";
    glyph.setAttribute("aria-hidden", "true");
    var name = document.createElement("span");
    name.textContent = strategy.charAt(0).toUpperCase() + strategy.slice(1);
    label.append(glyph, name);
    return label;
  }

  window.initConfigurationCockpit = function () {
    var cockpits = window.solarcleanCockpits || {};
    var mapLand = document.getElementById("cockpit-map-land");
    if (mapLand && typeof window.SOLARCLEAN_WORLD_LAND === "string") {
      mapLand.setAttribute("d", window.SOLARCLEAN_WORLD_LAND);
    }
    if (!configSelect) return;

    function setText(id, value) {
      var element = document.getElementById(id);
      if (element) element.textContent = value == null || value === "" ? "–" : String(value);
    }
    function renderCockpit() {
      var state = cockpits[configSelect.value];
      if (!state || state.error) {
        setText("cockpit-site", "Configuration unavailable");
        setText("cockpit-weather", "configuration error");
        return;
      }
      setText("cockpit-site", state.site_name);
      setText("cockpit-coordinates", state.latitude + ", " + state.longitude + " · " + state.timezone);
      setText("cockpit-assumptions", state.assumption_set);
      setText("cockpit-period", state.start_date + " — " + state.end_date);
      var weather = document.getElementById("cockpit-weather");
      if (weather) {
        weather.className = "readiness readiness-" + state.weather_status.state;
        weather.textContent = state.weather_status.label;
      }
      setText("cockpit-weather-detail", state.weather_status.detail);
      var marker = document.getElementById("cockpit-map-marker");
      if (marker) marker.setAttribute("transform", "translate(" + state.longitude + " " + (-state.latitude) + ")");
      // Frame the locator window around the configured site so the marker is
      // always in view, wherever in the world the configuration points.
      var mapSvg = document.getElementById("cockpit-map");
      var lon = Number(state.longitude);
      var lat = Number(state.latitude);
      if (mapSvg && isFinite(lon) && isFinite(lat)) {
        var windowW = 29;
        var windowH = 24;
        var viewX = clamp(lon - windowW / 2, -180, 180 - windowW);
        var viewY = clamp(-lat - windowH / 2, -90, 90 - windowH);
        mapSvg.setAttribute("viewBox", viewX + " " + viewY + " " + windowW + " " + windowH);
      }
      var winner = document.getElementById("cockpit-last-winner");
      if (winner) {
        winner.replaceChildren();
        if (state.last_run && state.last_run.winner) {
          winner.appendChild(strategyLabelNode(state.last_run.winner));
          if (state.last_run.margin_sar) {
            var margin = document.createElement("span");
            margin.className = "mono";
            margin.textContent = "+" + state.last_run.margin_sar + " SAR";
            winner.appendChild(document.createTextNode(" "));
            winner.appendChild(margin);
          }
        } else {
          winner.textContent = "No certified result";
        }
      }
      setText("cockpit-last-run", state.last_run ? state.last_run.run_id : "no matching run");
    }
    configSelect.addEventListener("change", renderCockpit);
    renderCockpit();
  };

  // --- KPI table micro-bars --------------------------------------------
  // Purely visual scaling of the stored values already printed in each row
  // (like a chart axis): bar length = |value| / row max. Nothing is derived
  // or displayed as a number.

  document.querySelectorAll(".kpi-table tbody tr").forEach(function (row) {
    var cells = Array.from(row.querySelectorAll("td[data-kpi-value]"));
    var values = cells.map(function (cell) {
      var value = parseFloat(cell.dataset.kpiValue);
      return isFinite(value) ? Math.abs(value) : NaN;
    });
    var max = Math.max.apply(null, values.filter(isFinite));
    if (!isFinite(max) || max <= 0) return;
    cells.forEach(function (cell, index) {
      if (!isFinite(values[index])) return;
      cell.classList.add("kpi-bar-cell");
      cell.style.setProperty("--kpi-bar", (values[index] / max * 100).toFixed(1) + "%");
    });
  });

  // --- charts ---------------------------------------------------------

  var liveCharts = [];
  var explorerCharts = [];
  var energyExplorerChart = null;
  var explorerEventChart = null;
  var explorerPayload = null;
  var explorerIndex = -1;
  var explorerLocked = false;
  var explorerScenario = "baseline";

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function chartInk() { return cssVar("--muted", "#5b6770"); }
  function chartGrid() { return cssVar("--line", "#d4d9d6"); }

  // Charts speak the console's language: axis ticks, legends, and tooltips
  // use the same mono stack as the tables. Chart.js loads after this file,
  // so defaults are applied lazily by the draw entry points.
  function applyChartTypography() {
    if (typeof Chart === "undefined") return;
    Chart.defaults.font.family = cssVar(
      "--mono", 'ui-monospace, "Cascadia Mono", Consolas, "Liberation Mono", Menlo, monospace'
    );
  }
  function scenarioColor(scenario) {
    return cssVar("--chart-" + scenario, cssVar("--ink", "#333"));
  }

  function strategyAxisLabel(scenario) {
    var marks = { baseline: "▤", reactive: "◊", coating: "⬡" };
    return (marks[scenario] || "") + " " + scenario;
  }

  function strategyPointStyle(scenario) {
    var glyph = document.createElement("canvas");
    glyph.width = 18;
    glyph.height = 18;
    var context = glyph.getContext("2d");
    context.strokeStyle = scenarioColor(scenario);
    context.lineWidth = 1.5;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.beginPath();
    if (scenario === "baseline") {
      context.rect(2.5, 5, 13, 8);
      context.moveTo(9, 5);
      context.lineTo(9, 13);
      context.moveTo(2.5, 9);
      context.lineTo(15.5, 9);
    } else if (scenario === "reactive") {
      context.moveTo(9, 2.5);
      context.bezierCurveTo(7, 6, 4.5, 8.5, 4.5, 11);
      context.bezierCurveTo(4.5, 14, 6.5, 15.5, 9, 15.5);
      context.bezierCurveTo(11.5, 15.5, 13.5, 14, 13.5, 11);
      context.bezierCurveTo(13.5, 8.5, 11, 6, 9, 2.5);
    } else if (scenario === "coating") {
      context.moveTo(5, 2.5);
      context.lineTo(13, 2.5);
      context.lineTo(16, 9);
      context.lineTo(13, 15.5);
      context.lineTo(5, 15.5);
      context.lineTo(2, 9);
      context.closePath();
    } else {
      context.arc(9, 9, 4, 0, Math.PI * 2);
    }
    context.stroke();
    return glyph;
  }

  function baseOptions(yLabel) {
    return {
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: chartInk(), usePointStyle: true, pointStyleWidth: 15 },
        },
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 14, font: { size: 11 }, color: chartInk() },
          grid: { color: chartGrid() },
        },
        y: {
          title: { display: !!yLabel, text: yLabel || "", font: { size: 11 }, color: chartInk() },
          ticks: { font: { size: 11 }, color: chartInk() },
          grid: { color: chartGrid() },
        },
      },
    };
  }

  function registerChart(chart) {
    liveCharts.push(chart);
    return chart;
  }

  // Re-read theme colours into existing charts after a theme toggle.
  function restyleCharts() {
    liveCharts.forEach(function (chart) {
      var ink = chartInk();
      var grid = chartGrid();
      if (chart.options.plugins.legend.labels) chart.options.plugins.legend.labels.color = ink;
      ["x", "y"].forEach(function (axis) {
        var scale = chart.options.scales[axis];
        if (!scale) return;
        if (scale.ticks) scale.ticks.color = ink;
        if (scale.grid) scale.grid.color = grid;
        if (scale.title) scale.title.color = ink;
      });
      chart.data.datasets.forEach(function (dataset) {
        if (dataset._kind === "reference") {
          dataset.borderColor = ink;
        }
        if (dataset._scenario) {
          var color = scenarioColor(dataset._scenario);
          dataset.borderColor = color;
          dataset.pointStyle = strategyPointStyle(dataset._scenario);
          if (dataset.type !== "line" && dataset.backgroundColor !== "transparent") {
            dataset.backgroundColor = color;
          }
        }
      });
      chart.update();
    });
  }

  function drawScenarioLines(canvasId, data, yLabel, seriesStyles) {
    var canvas = document.getElementById(canvasId);
    if (!data || !data.series || !canvas || typeof Chart === "undefined") return;
    var datasets = Object.keys(data.series).map(function (scenario) {
      var style = seriesStyles && seriesStyles[scenario];
      var colorScenario = style && style.colorScenario ? style.colorScenario : scenario;
      return {
        label: style && style.label ? style.label : scenario.charAt(0).toUpperCase() + scenario.slice(1),
        _scenario: colorScenario,
        data: data.series[scenario],
        borderColor: scenarioColor(colorScenario),
        pointStyle: strategyPointStyle(colorScenario),
        backgroundColor: "transparent",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0,
      };
    });
    registerChart(new Chart(canvas, {
      type: "line",
      data: { labels: data.dates, datasets: datasets },
      options: baseOptions(yLabel),
    }));
  }

  function baselineSeries(data) {
    if (!data || !data.series || !Array.isArray(data.series.baseline)) return null;
    return data.series.baseline;
  }

  function drawDewCementationLines(dew, cementation) {
    var source = dew || cementation;
    if (!source || !source.dates) return;

    var series = {};
    var styles = {};
    var dewSeries = baselineSeries(dew);
    var cementationSeries = baselineSeries(cementation);
    if (dewSeries) {
      series.dew = dewSeries;
      styles.dew = { label: "Dew risk", colorScenario: "baseline" };
    }
    if (cementationSeries) {
      series.cementation = cementationSeries;
      styles.cementation = { label: "Cementation index", colorScenario: "reactive" };
    }
    if (!Object.keys(series).length) return;

    drawScenarioLines(
      "daily-dew-chart", { dates: source.dates, series: series }, "Risk / index (0–1)", styles
    );
  }

  function finiteDisplay(value, digits) {
    return typeof value === "number" && isFinite(value) ? value.toFixed(digits) : "–";
  }

  function valueOnDate(data, date, seriesName) {
    if (!data || !Array.isArray(data.dates)) return null;
    var index = data.dates.indexOf(date);
    if (index < 0) return null;
    if (seriesName && data.series && Array.isArray(data.series[seriesName])) {
      return data.series[seriesName][index];
    }
    return Array.isArray(data.values) ? data.values[index] : null;
  }

  function setExplorerText(id, value) {
    var element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function friendlyDate(value) {
    var parsed = new Date(value + "T00:00:00");
    return isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString(undefined, {
      day: "numeric", month: "long", year: "numeric",
    });
  }

  function energyDisplay(value) {
    return finiteDisplay(value, 1) + " kWh";
  }

  var explorerCursorPlugin = {
    id: "solarcleanExplorerCursor",
    afterDatasetsDraw: function (chart) {
      if (typeof chart.$explorerIndex !== "number" || !chart.scales.x) return;
      var x = chart.scales.x.getPixelForValue(chart.$explorerIndex);
      var area = chart.chartArea;
      if (!area || !isFinite(x)) return;
      chart.ctx.save();
      chart.ctx.beginPath();
      chart.ctx.moveTo(x, area.top);
      chart.ctx.lineTo(x, area.bottom);
      chart.ctx.lineWidth = 1;
      chart.ctx.strokeStyle = cssVar("--sun-deep", "#c07f0e");
      chart.ctx.setLineDash([3, 3]);
      chart.ctx.stroke();
      chart.ctx.restore();
    },
  };

  function registerExplorerChart(chart) {
    explorerCharts.push(chart);
    return registerChart(chart);
  }

  function eventStyle(category) {
    return {
      rainfall: { color: "#2f7fa3", pointStyle: "rectRot", label: "Rain" },
      cleaning: { color: "#2f7d5c", pointStyle: "triangle", label: "Clean" },
      inspection: { color: "#c07f0e", pointStyle: "circle", label: "Inspect" },
      coating: { color: "#7b5aa6", pointStyle: "rect", label: "Coating" },
      contamination: { color: "#a3453c", pointStyle: "crossRot", label: "Contamination" },
    }[category];
  }

  function renderSelectedEvents(date) {
    var container = document.getElementById("selected-event-list");
    if (!container || !explorerPayload) return;
    container.replaceChildren();
    var rainfall = valueOnDate(explorerPayload.dailyRainfall, date);
    var displayEvents = (explorerPayload.dailyEventMarkers || []).filter(function (event) {
      return event.date === date &&
        (explorerScenario === "compare" || event.scenario === explorerScenario);
    });
    if (rainfall > 0) {
      displayEvents.unshift({ category: "rainfall", count: 1, rainfall_mm: rainfall });
    }
    if (!displayEvents.length) {
      var empty = document.createElement("span");
      empty.className = "hint";
      empty.textContent = "No stored events.";
      container.appendChild(empty);
      return;
    }
    displayEvents.forEach(function (event) {
      var pill = document.createElement("span");
      pill.className = "event-pill event-pill-" + event.category;
      if (event.category === "rainfall") {
        pill.textContent = "Rain " + finiteDisplay(event.rainfall_mm, 2) + " mm";
      } else {
        pill.textContent = (explorerScenario === "compare" ? event.scenario + " · " : "") +
          event.category + " ×" + event.count;
      }
      container.appendChild(pill);
    });
  }

  function renderSelectedDay() {
    if (!explorerPayload || explorerIndex < 0) return;
    var date = explorerPayload.dailyEnergy.dates[explorerIndex];
    setExplorerText("selected-day-date", friendlyDate(date));
    setExplorerText(
      "selected-clean-reference",
      energyDisplay(valueOnDate(explorerPayload.dailyCleanReference, date))
    );

    var scenarios = ["baseline", "reactive", "coating"];
    scenarios.forEach(function (scenario) {
      var row = document.querySelector('[data-selected-scenario="' + scenario + '"]');
      if (!row) return;
      row.hidden = explorerScenario !== "compare" && scenario !== explorerScenario;
      var actual = row.querySelector('[data-selected-field="actual"]');
      var loss = row.querySelector('[data-selected-field="loss"]');
      var cleanliness = row.querySelector('[data-selected-field="cleanliness"]');
      if (actual) actual.textContent = finiteDisplay(
        valueOnDate(explorerPayload.dailyEnergy, date, scenario), 1
      );
      if (loss) loss.textContent = finiteDisplay(
        valueOnDate(explorerPayload.dailyLoss, date, scenario), 1
      );
      if (cleanliness) cleanliness.textContent = finiteDisplay(
        valueOnDate(explorerPayload.dailySoiling, date, scenario), 4
      );
    });

    var reference = valueOnDate(explorerPayload.dailyCleanReference, date);
    if (explorerScenario === "compare") {
      setExplorerText(
        "selected-day-summary",
        "The clean reference is shared. Compare each scenario's exact loss and cleanliness gap."
      );
    } else {
      var actualValue = valueOnDate(explorerPayload.dailyEnergy, date, explorerScenario);
      var lossValue = valueOnDate(explorerPayload.dailyLoss, date, explorerScenario);
      setExplorerText(
        "selected-day-summary",
        explorerScenario + " delivered " + energyDisplay(actualValue) + " from " +
        energyDisplay(reference) + " of modeled clean potential; the stored scenario gap was " +
        energyDisplay(lossValue) + "."
      );
    }

    var weather = explorerPayload.dailyWeather;
    var weatherIndex = weather && Array.isArray(weather.dates) ? weather.dates.indexOf(date) : -1;
    setExplorerText(
      "selected-ghi",
      weatherIndex >= 0 ? finiteDisplay(weather.daily_ghi_irradiation_kwh_m2[weatherIndex], 2) +
        " kWh/m²" : "–"
    );
    setExplorerText(
      "selected-ambient-temperature",
      weatherIndex >= 0 ? finiteDisplay(
        weather.daylight_mean_ambient_temperature_c[weatherIndex], 1
      ) + " °C" : "–"
    );
    setExplorerText(
      "selected-cell-temperature",
      weatherIndex >= 0 ? finiteDisplay(
        weather.daylight_mean_cell_temperature_c[weatherIndex], 1
      ) + " °C" : "–"
    );
    setExplorerText(
      "selected-rainfall",
      finiteDisplay(valueOnDate(explorerPayload.dailyRainfall, date), 2) + " mm"
    );
    renderSelectedEvents(date);
  }

  function updateFollowHoverButton() {
    var button = document.getElementById("follow-hover-button");
    if (!button) return;
    button.disabled = !explorerLocked;
    button.textContent = explorerLocked ? "Resume hover" : "Following hover";
  }

  function setExplorerIndex(index, lockSelection) {
    if (!explorerPayload || !explorerPayload.dailyEnergy || explorerLocked && !lockSelection) return;
    var lastIndex = explorerPayload.dailyEnergy.dates.length - 1;
    var nextIndex = Math.max(0, Math.min(lastIndex, Math.round(index)));
    if (lockSelection) explorerLocked = true;
    if (nextIndex === explorerIndex && !lockSelection) return;
    explorerIndex = nextIndex;
    explorerCharts.forEach(function (chart) {
      chart.$explorerIndex = nextIndex;
      chart.draw();
    });
    updateFollowHoverButton();
    renderSelectedDay();
  }

  function explorerIndexFromEvent(chart, event) {
    if (!chart.scales.x || typeof event.x !== "number") return null;
    var value = chart.scales.x.getValueForPixel(event.x);
    return typeof value === "number" && isFinite(value) ? value : null;
  }

  function wireExplorerInteraction(options, showTooltip) {
    options.maintainAspectRatio = false;
    options.plugins.tooltip = options.plugins.tooltip || {};
    options.plugins.tooltip.enabled = showTooltip;
    options.onHover = function (event, _elements, chart) {
      var index = explorerIndexFromEvent(chart, event);
      if (index !== null) setExplorerIndex(index, false);
    };
    options.onClick = function (event, _elements, chart) {
      var index = explorerIndexFromEvent(chart, event);
      if (index !== null) setExplorerIndex(index, true);
    };
    if (options.scales.y) {
      options.scales.y.afterFit = function (scale) { scale.width = 58; };
    }
    return options;
  }

  function trackOptions(showDates) {
    var options = wireExplorerInteraction(baseOptions(""), false);
    options.plugins.legend.display = false;
    options.scales.x.ticks.display = showDates;
    options.scales.x.grid.display = false;
    options.scales.y.ticks.maxTicksLimit = 3;
    return options;
  }

  function eventTrackDatasets(payload) {
    var grouped = {};
    (payload.dailyEventMarkers || []).forEach(function (event) {
      var style = eventStyle(event.category);
      if (!style) return;
      var key = event.scenario + "|" + event.category;
      grouped[key] = grouped[key] || {
        category: event.category, scenario: event.scenario, points: [],
      };
      grouped[key].points.push({ x: event.date, y: style.label });
    });
    if (payload.dailyRainfall && Array.isArray(payload.dailyRainfall.dates)) {
      grouped["shared|rainfall"] = { category: "rainfall", scenario: null, points: [] };
      payload.dailyRainfall.dates.forEach(function (date, index) {
        if (payload.dailyRainfall.values[index] > 0) {
          grouped["shared|rainfall"].points.push({ x: date, y: "Rain" });
        }
      });
    }
    return Object.keys(grouped).map(function (key) {
      var group = grouped[key];
      var style = eventStyle(group.category);
      return {
        label: style.label,
        _filterScenario: group.scenario,
        data: group.points,
        showLine: false,
        pointRadius: 4,
        pointHoverRadius: 5,
        pointStyle: style.pointStyle,
        borderColor: style.color,
        backgroundColor: style.color,
      };
    });
  }

  function drawContextTracks(payload) {
    var dates = payload.dailyEnergy.dates;
    var weather = payload.dailyWeather;
    var ghiCanvas = document.getElementById("daily-ghi-chart");
    if (weather && ghiCanvas) {
      var ghiOptions = trackOptions(false);
      ghiOptions.scales.y.beginAtZero = true;
      registerExplorerChart(new Chart(ghiCanvas, {
        type: "bar",
        data: { labels: dates, datasets: [{
          label: "Daily GHI",
          data: weather.daily_ghi_irradiation_kwh_m2,
          backgroundColor: cssVar("--sun-deep", "#c07f0e"),
          borderWidth: 0,
          barPercentage: 1,
          categoryPercentage: 1,
        }] },
        options: ghiOptions,
        plugins: [explorerCursorPlugin],
      }));
    }

    var temperatureCanvas = document.getElementById("daily-temperature-chart");
    if (weather && temperatureCanvas) {
      registerExplorerChart(new Chart(temperatureCanvas, {
        type: "line",
        data: { labels: dates, datasets: [
          {
            label: "Ambient",
            data: weather.daylight_mean_ambient_temperature_c,
            borderColor: "#2f7fa3",
            backgroundColor: "transparent",
            pointRadius: 0,
            borderWidth: 1.25,
          },
          {
            label: "Module/cell",
            data: weather.daylight_mean_cell_temperature_c,
            borderColor: "#a3453c",
            backgroundColor: "transparent",
            pointRadius: 0,
            borderWidth: 1.25,
          },
        ] },
        options: trackOptions(false),
        plugins: [explorerCursorPlugin],
      }));
    }

    var rainfallCanvas = document.getElementById("daily-rainfall-chart");
    if (payload.dailyRainfall && rainfallCanvas) {
      var rainfallOptions = trackOptions(false);
      rainfallOptions.scales.y.beginAtZero = true;
      registerExplorerChart(new Chart(rainfallCanvas, {
        type: "bar",
        data: { labels: dates, datasets: [{
          label: "Rainfall",
          data: payload.dailyRainfall.values,
          backgroundColor: "#2f7fa3",
          borderWidth: 0,
          barPercentage: 1,
          categoryPercentage: 1,
        }] },
        options: rainfallOptions,
        plugins: [explorerCursorPlugin],
      }));
    }

    var eventCanvas = document.getElementById("daily-events-chart");
    if (eventCanvas) {
      var eventOptions = trackOptions(true);
      eventOptions.scales.y.type = "category";
      eventOptions.scales.y.labels = ["Rain", "Clean", "Inspect", "Coating", "Contamination"];
      eventOptions.scales.y.ticks.display = false;
      explorerEventChart = registerExplorerChart(new Chart(eventCanvas, {
        type: "line",
        data: { labels: dates, datasets: eventTrackDatasets(payload) },
        options: eventOptions,
        plugins: [explorerCursorPlugin],
      }));
    }
  }

  function applyExplorerScenario(scenario) {
    explorerScenario = scenario;
    document.querySelectorAll("[data-energy-scenario]").forEach(function (button) {
      var selected = button.getAttribute("data-energy-scenario") === scenario;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    if (energyExplorerChart) {
      energyExplorerChart.data.datasets.forEach(function (dataset) {
        if (dataset._kind === "actual") {
          dataset.hidden = scenario !== "compare" && dataset._scenario !== scenario;
        }
      });
      energyExplorerChart.update();
    }
    if (explorerEventChart) {
      explorerEventChart.data.datasets.forEach(function (dataset) {
        dataset.hidden = dataset._filterScenario && scenario !== "compare" &&
          dataset._filterScenario !== scenario;
      });
      explorerEventChart.update();
    }
    renderSelectedDay();
  }

  function drawEnergyExplorer(payload) {
    var data = payload.dailyEnergy;
    var canvas = document.getElementById("daily-energy-chart");
    if (!data || !data.series || !canvas || typeof Chart === "undefined") return;
    explorerPayload = payload;
    var datasets = Object.keys(data.series).map(function (scenario) {
      return {
        label: scenario.charAt(0).toUpperCase() + scenario.slice(1) + " actual",
        _kind: "actual",
        _scenario: scenario,
        hidden: scenario !== "baseline",
        data: data.series[scenario],
        borderColor: scenarioColor(scenario),
        pointStyle: strategyPointStyle(scenario),
        backgroundColor: "transparent",
        borderWidth: 1.8,
        pointRadius: 0,
        tension: 0,
      };
    });
    if (payload.dailyCleanReference && Array.isArray(payload.dailyCleanReference.values)) {
      datasets.push({
        label: "Clean reference",
        _kind: "reference",
        data: payload.dailyCleanReference.values,
        borderColor: chartInk(),
        backgroundColor: "transparent",
        borderDash: [7, 4],
        borderWidth: 1.4,
        pointRadius: 0,
        tension: 0,
      });
    }
    var options = wireExplorerInteraction(baseOptions("AC energy (kWh/day)"), true);
    options.plugins.tooltip.callbacks = {
      label: function (context) {
        return context.dataset.label + ": " + energyDisplay(context.parsed.y);
      },
    };
    energyExplorerChart = registerExplorerChart(new Chart(canvas, {
      type: "line",
      data: { labels: data.dates, datasets: datasets },
      options: options,
      plugins: [explorerCursorPlugin],
    }));
    // Keyboard day-stepping: arrows move the locked selection so the
    // selected-day panel is usable without a mouse.
    canvas.addEventListener("keydown", function (event) {
      var step = event.shiftKey ? 7 : 1;
      var lastIndex = data.dates.length - 1;
      var target = null;
      if (event.key === "ArrowLeft") target = (explorerIndex < 0 ? 0 : explorerIndex) - step;
      else if (event.key === "ArrowRight") target = (explorerIndex < 0 ? 0 : explorerIndex) + step;
      else if (event.key === "Home") target = 0;
      else if (event.key === "End") target = lastIndex;
      if (target === null) return;
      event.preventDefault();
      setExplorerIndex(target, true);
    });
    drawContextTracks(payload);
    document.querySelectorAll("[data-energy-scenario]").forEach(function (button) {
      button.addEventListener("click", function () {
        applyExplorerScenario(button.getAttribute("data-energy-scenario"));
      });
    });
    var followButton = document.getElementById("follow-hover-button");
    if (followButton) {
      followButton.addEventListener("click", function () {
        explorerLocked = false;
        updateFollowHoverButton();
      });
    }
    applyExplorerScenario("baseline");
    setExplorerIndex(0, false);
  }

  function drawDustCalendars(payload) {
    if (!payload || !Array.isArray(payload.dates) || !payload.dates.length) return;
    document.querySelectorAll("[data-calendar-scenario]").forEach(function (calendar) {
      var scenario = calendar.dataset.calendarScenario;
      var values = payload.series && payload.series[scenario];
      if (!Array.isArray(values)) return;
      calendar.replaceChildren();
      var first = new Date(payload.dates[0] + "T00:00:00Z");
      var mondayOffset = (first.getUTCDay() + 6) % 7;
      for (var blankIndex = 0; blankIndex < mondayOffset; blankIndex += 1) {
        var blank = document.createElement("span");
        blank.className = "dust-day dust-day-placeholder";
        blank.setAttribute("aria-hidden", "true");
        calendar.appendChild(blank);
      }
      payload.dates.forEach(function (date, index) {
        var cell = document.createElement("span");
        var value = values[index];
        var dust = typeof value === "number" ? clamp((1 - value) / 0.3, 0, 1) : 0;
        cell.className = "dust-day";
        cell.style.setProperty("--day-color", "rgba(151, 105, 48, " + (0.08 + dust * 0.88) + ")");
        var events = payload.events && payload.events[scenario] && payload.events[scenario][date] || [];
        events.forEach(function (category) { cell.classList.add("is-" + category); });
        cell.title = date + " · cleanliness " +
          (typeof value === "number" ? value.toFixed(4) : "–") +
          (events.length ? " · " + events.join(", ") : "");
        cell.setAttribute("aria-label", cell.title);
        calendar.appendChild(cell);
      });
    });
  }

  function initDustCalendars(payload) {
    var panel = document.querySelector(".dust-calendar-panel");
    if (!panel || !payload.dailySoiling) return;
    var events = {};
    (payload.dailyEventMarkers || []).forEach(function (marker) {
      var scenarioEvents = events[marker.scenario] || (events[marker.scenario] = {});
      var dayEvents = scenarioEvents[marker.date] || (scenarioEvents[marker.date] = []);
      if (dayEvents.indexOf(marker.category) === -1) dayEvents.push(marker.category);
    });
    var rendered = false;
    var render = function () {
      if (rendered || !panel.open) return;
      drawDustCalendars({
        dates: payload.dailySoiling.dates,
        series: payload.dailySoiling.series,
        events: events,
      });
      rendered = true;
    };
    panel.addEventListener("toggle", render);
    render();
  }

  // Offer a PNG export next to each standalone chart. The image is exactly
  // the rendered canvas on the theme's surface colour — no data is re-read.
  var _downloadableCharts = [
    "daily-energy-chart", "daily-loss-chart", "daily-soiling-chart", "daily-dew-chart",
    "daily-cumgain-chart", "annual-cost-chart", "mc-trials-chart", "mc-win-chart",
    "mc-benefit-chart", "tornado-chart", "breakeven-chart",
  ];
  function addChartDownloads() {
    _downloadableCharts.forEach(function (id) {
      var canvas = document.getElementById(id);
      if (!canvas || canvas.dataset.downloadBound) return;
      canvas.dataset.downloadBound = "true";
      var button = document.createElement("button");
      button.type = "button";
      button.className = "chart-download";
      button.textContent = "download chart PNG";
      button.addEventListener("click", function () {
        var out = document.createElement("canvas");
        out.width = canvas.width;
        out.height = canvas.height;
        var context = out.getContext("2d");
        context.fillStyle = cssVar("--surface", "#ffffff");
        context.fillRect(0, 0, out.width, out.height);
        context.drawImage(canvas, 0, 0);
        var link = document.createElement("a");
        link.href = out.toDataURL("image/png");
        link.download = (document.title.split(" · ")[0] || "solarclean") + "-" + id + ".png";
        link.click();
      });
      var host = canvas.closest(".energy-main-chart") || canvas;
      host.insertAdjacentElement("afterend", button);
    });
  }

  // Called from the comparison template after Chart.js loads. Data comes
  // straight from the run's stored CSV artifacts via the server.
  window.drawComparisonCharts = function () {
    applyChartTypography();
    var payload = window.solarcleanCharts || {};
    initDustCalendars(payload);
    drawEnergyExplorer(payload);
    drawScenarioLines("daily-loss-chart", payload.dailyLoss, "Energy loss (kWh/day)");
    drawScenarioLines(
      "daily-soiling-chart", payload.dailySoiling, "Dust / contamination cleanliness (1 = clean)"
    );
    drawDewCementationLines(payload.dailyDew, payload.dailyCementation);
    drawScenarioLines(
      "daily-cumgain-chart", payload.dailyCumGain, "Cumulative gain vs baseline (kWh)"
    );

    addChartDownloads();
    var bars = payload.annualCostBars;
    var canvas = document.getElementById("annual-cost-chart");
    if (bars && canvas && typeof Chart !== "undefined") {
      var metricColors = ["#2f7d5c", "#8a5a10", "#a3453c", "#16405b"];
      registerChart(new Chart(canvas, {
        type: "bar",
        data: {
          labels: bars.scenarios.map(strategyAxisLabel),
          datasets: bars.metrics.map(function (metric, i) {
            return {
              label: metric.label,
              data: metric.values,
              backgroundColor: metricColors[i % metricColors.length],
            };
          }),
        },
        options: baseOptions("SAR/year"),
      }));
    }
  };

  // Analysis results pages: charts of stored artifact values only.
  window.drawAnalysisCharts = function () {
    if (typeof Chart === "undefined") return;
    applyChartTypography();
    drawMonteCarloSummaryCharts(window.solarcleanMonteCarlo);
    drawMcTrialsChart(window.solarcleanMcTrials);
    drawTornadoChart(window.solarcleanTornado);
    drawBreakEvenChart(window.solarcleanBreakEven);
    addChartDownloads();
  };

  // Per-trial net benefit dot plot: one dot per reconciled trial per scenario.
  // Dots are fanned out vertically in a fixed pattern purely so they do not
  // overprint — the vertical offset carries no meaning.
  function drawMcTrialsChart(payload) {
    var canvas = document.getElementById("mc-trials-chart");
    if (!payload || !payload.series || !canvas) return;
    var scenarios = Object.keys(payload.series);
    var datasets = scenarios.map(function (scenario, row) {
      return {
        label: scenario,
        _scenario: scenario,
        data: payload.series[scenario].map(function (value, i) {
          return { x: value, y: row + ((i % 7) - 3) * 0.07 };
        }),
        backgroundColor: scenarioColor(scenario),
        pointStyle: strategyPointStyle(scenario),
        pointRadius: 3,
      };
    });
    var options = baseOptions("");
    options.scales.x.title = {
      display: true, text: "Net annual benefit (SAR)", font: { size: 11 }, color: chartInk(),
    };
    options.scales.x.type = "linear";
    options.scales.y.min = -0.6;
    options.scales.y.max = scenarios.length - 0.4;
    options.scales.y.ticks.callback = function (value) {
      return Number.isInteger(value) ? strategyAxisLabel(scenarios[value]) : "";
    };
    options.interaction = { mode: "nearest", intersect: false };
    registerChart(new Chart(canvas, { type: "scatter", data: { datasets: datasets }, options: options }));
  }

  // Tornado chart: stored net-benefit swing per parameter, largest first.
  function drawTornadoChart(payload) {
    var canvas = document.getElementById("tornado-chart");
    if (!payload || !payload.entries || !canvas) return;
    var options = baseOptions("");
    options.indexAxis = "y";
    options.plugins.legend.display = false;
    options.scales.x.title = {
      display: true, text: "Net annual benefit swing (SAR)", font: { size: 11 }, color: chartInk(),
    };
    options.scales.y.ticks.autoSkip = false;
    registerChart(new Chart(canvas, {
      type: "bar",
      data: {
        labels: payload.entries.map(function (entry) { return entry.parameter; }),
        datasets: [{
          label: "swing (SAR)",
          data: payload.entries.map(function (entry) { return entry.swing_sar; }),
          backgroundColor: payload.entries.map(function (entry) {
            return entry.winner_changed ? "#c07f0e" : cssVar("--chart-reactive", "#16405b");
          }),
        }],
      },
      options: options,
    }));
  }

  // Break-even: stored margin at each evaluated value, zero line, crossings.
  function drawBreakEvenChart(payload) {
    var canvas = document.getElementById("breakeven-chart");
    if (!payload || !payload.points || !canvas) return;
    var xs = payload.points.map(function (point) { return point.x; });
    var xMin = Math.min.apply(null, xs);
    var xMax = Math.max.apply(null, xs);
    var datasets = [
      {
        label: "margin (SAR)",
        data: payload.points,
        borderColor: cssVar("--chart-reactive", "#16405b"),
        backgroundColor: cssVar("--chart-reactive", "#16405b"),
        showLine: true,
        borderWidth: 1.5,
        pointRadius: 3,
      },
      {
        label: "tie (margin = 0)",
        data: [{ x: xMin, y: 0 }, { x: xMax, y: 0 }],
        borderColor: cssVar("--muted", "#5b6770"),
        borderDash: [6, 4],
        borderWidth: 1,
        pointRadius: 0,
        showLine: true,
      },
    ];
    if (payload.crossovers && payload.crossovers.length) {
      datasets.push({
        label: "break-even",
        data: payload.crossovers.map(function (value) { return { x: value, y: 0 }; }),
        backgroundColor: "#c0392b",
        pointRadius: 5,
        pointStyle: "rectRot",
      });
    }
    var options = baseOptions("Margin (SAR/year)");
    options.scales.x.type = "linear";
    options.scales.x.title = {
      display: true,
      text: String(payload.parameter_name || "parameter value"),
      font: { size: 11 },
      color: chartInk(),
    };
    registerChart(new Chart(canvas, { type: "scatter", data: { datasets: datasets }, options: options }));
  }

  // Monte Carlo summary bar charts (win probability + spread).
  function drawMonteCarloSummaryCharts(summary) {
    if (!summary || !summary.scenario_summaries) return;
    var scenarios = Object.keys(summary.scenario_summaries);

    var winCanvas = document.getElementById("mc-win-chart");
    if (winCanvas) {
      var winOptions = baseOptions("Win probability");
      winOptions.scales.y.min = 0;
      winOptions.scales.y.max = 1;
      registerChart(new Chart(winCanvas, {
        type: "bar",
        data: {
          labels: scenarios.map(strategyAxisLabel),
          datasets: [{
            label: "win probability",
            data: scenarios.map(function (sid) {
              return summary.scenario_summaries[sid].win_probability;
            }),
            backgroundColor: scenarios.map(scenarioColor),
          }],
        },
        options: winOptions,
      }));
    }

    var benefitCanvas = document.getElementById("mc-benefit-chart");
    if (benefitCanvas) {
      var stats = [
        { key: "p5_net_annual_benefit_sar", label: "P5" },
        { key: "mean_net_annual_benefit_sar", label: "mean" },
        { key: "p95_net_annual_benefit_sar", label: "P95" },
      ];
      var statColors = ["#8a5a10", "#16405b", "#2f7d5c"];
      registerChart(new Chart(benefitCanvas, {
        type: "bar",
        data: {
          labels: scenarios.map(strategyAxisLabel),
          datasets: stats.map(function (stat, i) {
            return {
              label: stat.label,
              data: scenarios.map(function (sid) {
                return summary.scenario_summaries[sid][stat.key];
              }),
              backgroundColor: statColors[i],
            };
          }),
        },
        options: baseOptions("Net annual benefit (SAR)"),
      }));
    }
  }
})();
