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

  // --- anchored popovers ------------------------------------------------
  // One positioning helper serves the audit source trace and the info
  // popovers that replaced title-attribute tooltips (titles are invisible to
  // keyboard and touch). Popovers show text already rendered into data
  // attributes; nothing is fetched or derived.

  function anchorPopover(popover, target) {
    popover.hidden = false;
    popover.style.visibility = "hidden";
    popover.style.left = "0px";
    popover.style.top = "0px";
    var rect = target.getBoundingClientRect();
    var width = popover.offsetWidth;
    var height = popover.offsetHeight;
    var margin = 8;
    var left = Math.min(
      Math.max(margin, rect.left),
      window.innerWidth - width - margin
    );
    var top = rect.bottom + 6;
    if (top + height > window.innerHeight - margin) {
      top = Math.max(margin, rect.top - height - 6);
    }
    popover.style.left = left + "px";
    popover.style.top = top + "px";
    popover.style.visibility = "";
  }

  // --- audit mode -----------------------------------------------------
  // The source trace is an interaction layer over stored figures. It never
  // fetches or derives another value; it reveals the artifact annotations
  // already attached to the rendered element.

  var auditToggle = document.getElementById("audit-toggle");
  var auditPopover = document.getElementById("audit-popover");
  var auditBanner = document.getElementById("audit-banner");
  var auditKeyboardSelector =
    'a[href], button, input, select, textarea, summary, [contenteditable="true"], [tabindex]';
  var auditInteractiveDescendantSelector =
    'a[href], button, input, select, textarea, summary, [contenteditable="true"]';

  function setAuditSourceKeyboardState(enabled) {
    document.querySelectorAll("[data-audit-source]").forEach(function (target) {
      var naturallyKeyboardAccessible = target.matches(auditKeyboardSelector);
      var containsInteractiveControl = Boolean(
        target.querySelector(auditInteractiveDescendantSelector)
      );
      if (enabled && !naturallyKeyboardAccessible && !containsInteractiveControl &&
          !target.hasAttribute("tabindex")) {
        target.setAttribute("tabindex", "0");
        target.dataset.auditTabindexAdded = "true";
        if (!target.hasAttribute("aria-label")) {
          var visibleValue = target.textContent.trim().replace(/\s+/g, " ").slice(0, 100);
          target.setAttribute(
            "aria-label",
            "Show stored source for " + (visibleValue || "this value") + ": " +
              target.dataset.auditSource
          );
          target.dataset.auditAriaLabelAdded = "true";
        }
      } else if (!enabled && target.dataset.auditTabindexAdded === "true") {
        target.removeAttribute("tabindex");
        if (target.dataset.auditAriaLabelAdded === "true") target.removeAttribute("aria-label");
        delete target.dataset.auditTabindexAdded;
        delete target.dataset.auditAriaLabelAdded;
      }
    });
  }

  function openAuditPopover(target) {
    if (!auditPopover || !target) return;
    document.getElementById("audit-popover-title").textContent =
      target.dataset.auditSource || "Stored artifact";
    document.getElementById("audit-popover-detail").textContent =
      target.dataset.auditDetail || "This figure is read from the named stored artifact.";
    var check = document.getElementById("audit-popover-check");
    check.textContent = target.dataset.auditCheck || "";
    check.hidden = !target.dataset.auditCheck;
    anchorPopover(auditPopover, target);
  }

  function setAuditMode(enabled) {
    document.body.classList.toggle("audit-mode", enabled);
    if (auditToggle) auditToggle.setAttribute("aria-pressed", enabled ? "true" : "false");
    if (auditBanner) auditBanner.hidden = !enabled;
    if (!enabled && auditPopover) auditPopover.hidden = true;
    setAuditSourceKeyboardState(enabled);
  }
  if (auditToggle) {
    auditToggle.addEventListener("click", function () {
      setAuditMode(!document.body.classList.contains("audit-mode"));
    });
  }
  document.querySelectorAll(".footer-audit-toggle").forEach(function (button) {
    button.addEventListener("click", function () { setAuditMode(true); });
  });
  var auditBannerExit = document.getElementById("audit-banner-exit");
  if (auditBannerExit) {
    auditBannerExit.addEventListener("click", function () { setAuditMode(false); });
  }
  document.addEventListener("click", function (event) {
    if (!document.body.classList.contains("audit-mode") || !auditPopover) return;
    var target = event.target.closest("[data-audit-source]");
    if (!target) return;
    var action = event.target.closest(auditInteractiveDescendantSelector);
    if (action && action !== target) return;
    event.preventDefault();
    openAuditPopover(target);
  });
  var auditClose = document.querySelector(".audit-close");
  if (auditClose) auditClose.addEventListener("click", function () { auditPopover.hidden = true; });
  document.addEventListener("keydown", function (event) {
    if ((event.key === "Enter" || event.key === " ") &&
        document.body.classList.contains("audit-mode") &&
        event.target instanceof Element && event.target.matches("[data-audit-source]")) {
      event.preventDefault();
      openAuditPopover(event.target);
      return;
    }
    if (event.key !== "Escape") return;
    if (auditPopover && !auditPopover.hidden) {
      auditPopover.hidden = true;
      return;
    }
    if (document.body.classList.contains("audit-mode")) setAuditMode(false);
  });
  if (auditPopover) auditPopover.setAttribute("aria-live", "polite");

  // --- info popovers (accessible replacement for title tooltips) --------

  var infoPopover = document.getElementById("info-popover");
  function hideInfoPopover() {
    if (infoPopover) infoPopover.hidden = true;
  }
  if (infoPopover) {
    document.addEventListener("click", function (event) {
      var target = event.target.closest("[data-pop]");
      if (!target) {
        hideInfoPopover();
        return;
      }
      if (document.body.classList.contains("audit-mode") &&
          target.closest("[data-audit-source]")) {
        return; // audit trace wins while audit mode is armed
      }
      var text = target.dataset.pop;
      if (!text) return;
      if (!infoPopover.hidden && infoPopover.$popTarget === target) {
        hideInfoPopover();
        return;
      }
      infoPopover.textContent = text;
      infoPopover.$popTarget = target;
      anchorPopover(infoPopover, target);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") hideInfoPopover();
      if ((event.key === "Enter" || event.key === " ") &&
          event.target instanceof Element && event.target.matches("[data-pop]")) {
        event.preventDefault();
        event.target.click();
      }
    });
    window.addEventListener("scroll", hideInfoPopover, { passive: true });
  }

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

  // The launcher asks the question first: analysis kinds are radio cards
  // ("Which strategy wins?"), and the method-specific fields follow.
  var kindCards = document.getElementById("kind-cards");
  function selectedKind() {
    var checked = kindCards && kindCards.querySelector('input[name="kind"]:checked');
    return checked ? checked.value : "compare";
  }
  function updateOneWayWorkload() {
    var select = document.getElementById("parameters");
    var stepsInput = document.getElementById("steps");
    var output = document.getElementById("oneway-workload");
    if (!select || !stepsInput || !output) return;
    var selected = Array.from(select.selectedOptions);
    output.classList.remove("sensitivity-workload-heavy");
    if (!selected.length) {
      output.textContent = "Choose at least one parameter to calculate the workload.";
      return;
    }
    var steps = Math.max(3, parseInt(stepsInput.value, 10) || 5);
    var evaluations = 1;
    selected.forEach(function (option) {
      evaluations += Number(option.dataset.low) === Number(option.dataset.high) ? 1 : steps;
    });
    var exhaustive = selected.length === select.options.length;
    output.textContent = selected.length + (selected.length === 1 ? " parameter" : " parameters") +
      " · " + evaluations + " comparison evaluations. Each evaluation compares Baseline, " +
      "Reactive, and Coating." + (exhaustive ? " Exhaustive sweep — expect a long run." : "");
    output.classList.toggle("sensitivity-workload-heavy", exhaustive || evaluations > 50);
  }
  window.updateOneWayWorkload = updateOneWayWorkload;
  var stepsInput = document.getElementById("steps");
  var oneWayParameters = document.getElementById("parameters");
  if (stepsInput) stepsInput.addEventListener("input", updateOneWayWorkload);
  if (oneWayParameters) oneWayParameters.addEventListener("change", updateOneWayWorkload);
  updateOneWayWorkload();
  if (kindCards) {
    var showOptionsForKind = function () {
      document.querySelectorAll(".kind-opts").forEach(function (row) {
        var active = row.dataset.kind === selectedKind();
        row.hidden = !active;
        row.querySelectorAll("input, select, textarea, button").forEach(function (control) {
          if (!active && !control.disabled) {
            control.disabled = true;
            control.dataset.kindDisabled = "true";
          } else if (active && control.dataset.kindDisabled === "true") {
            control.disabled = false;
            delete control.dataset.kindDisabled;
          }
        });
      });
      if (selectedKind() === "sensitivity-oneway") updateOneWayWorkload();
      updateLaunchExpectations();
    };
    kindCards.addEventListener("change", showOptionsForKind);
    showOptionsForKind();
  }

  var configSelect = document.getElementById("config");
  var configLink = document.getElementById("config-link");
  if (configSelect && configLink) {
    var parameterCatalogSequence = 0;
    var parameterCatalogController = null;
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
          option.dataset.low = parameter.low;
          option.dataset.high = parameter.high;
          option.selected = chosen.has(parameter.name) ||
            (id === "parameter-b" && chosen.size === 0 && index === 1);
          select.appendChild(option);
        });
      });
      if (window.initParameterPickers) window.initParameterPickers(parameters);
      updateOneWayWorkload();
    };
    var updateConfigLink = function () {
      configLink.href = "/config/" + encodeURIComponent(configSelect.value);
      var cockpitMapLink = document.getElementById("cockpit-map-link");
      if (cockpitMapLink) {
        cockpitMapLink.href =
          "/config/" + encodeURIComponent(configSelect.value) + "#site-location";
      }
    };
    configSelect.addEventListener("change", function () {
      updateConfigLink();
      updateSimulationPeriod();
      updateLaunchExpectations();
      var requestedConfig = configSelect.value;
      var requestSequence = ++parameterCatalogSequence;
      if (parameterCatalogController) parameterCatalogController.abort();
      parameterCatalogController = typeof AbortController !== "undefined"
        ? new AbortController() : null;
      var fetchOptions = parameterCatalogController
        ? { signal: parameterCatalogController.signal } : {};
      fetch("/api/configs/" + encodeURIComponent(requestedConfig) + "/parameters", fetchOptions)
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then(function (parameters) {
          if (requestSequence !== parameterCatalogSequence ||
              configSelect.value !== requestedConfig) return;
          updateParameterCatalog(parameters);
        })
        .catch(function (error) {
          if (error.name === "AbortError") return;
          // The launch endpoint remains the authoritative registry validator.
        });
    });
    updateConfigLink();
    updateSimulationPeriod();
  }

  // --- launching runs -----------------------------------------------------

  var launchButton = document.getElementById("launch");
  var launchForm = document.getElementById("launch-form");
  if (launchButton && launchForm) {
    // Restore native form semantics even though older templates cancel their
    // inline submit handler. Enter now submits, and the browser applies its
    // required/min/max validation before this listener runs.
    launchForm.onsubmit = null;
    launchButton.type = "submit";
    launchForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (launchButton.disabled) return;
      var errorEl = document.getElementById("launch-error");
      errorEl.textContent = "";

      var body = { kind: selectedKind(), config: configSelect.value };
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
        if (!chosen.length) {
          errorEl.textContent = "Choose at least one parameter for one-way sensitivity.";
          return;
        }
        body.parameters = chosen;
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
        if (body.scenario_a === body.scenario_b) {
          errorEl.textContent = "Pick two different scenarios for the break-even search.";
          return;
        }
      }

      // Ask only after validation, while submission is still a user gesture.
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        try { Notification.requestPermission(); } catch (e) { /* unsupported */ }
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
          addJobCard(job);
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

  // Launch timing is a display of persisted dashboard-job history. It is not
  // an estimate: the newest finished record matching method + config is shown
  // verbatim, with its stored elapsed_seconds formatted for reading.
  function launchHistoryRecords() {
    var payload = window.solarcleanJobHistory;
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.jobs)) return payload.jobs;
    if (payload && Array.isArray(payload.records)) return payload.records;
    return [];
  }

  function jobHistoryConfig(record) {
    return record && (record.config_name || record.config || record.configName);
  }

  function jobHistoryFinished(record) {
    return record && ["done", "finished", "complete", "completed"].indexOf(record.status) >= 0 &&
      typeof record.elapsed_seconds === "number" && isFinite(record.elapsed_seconds);
  }

  function matchingFinishedJob(kind, configName) {
    var matches = launchHistoryRecords().filter(function (record) {
      return jobHistoryFinished(record) && record.kind === kind &&
        jobHistoryConfig(record) === configName;
    });
    matches.sort(function (left, right) {
      var leftTime = Date.parse(
        left.finished_at || left.updated_at || left.created_at || ""
      ) || 0;
      var rightTime = Date.parse(
        right.finished_at || right.updated_at || right.created_at || ""
      ) || 0;
      return rightTime - leftTime;
    });
    return matches[0] || null;
  }

  function launchKindLabel(kind) {
    return {
      compare: "compare-all-scenarios",
      "monte-carlo": "Monte Carlo",
      "sensitivity-oneway": "one-way sensitivity",
      "winner-map": "winner map",
      "break-even": "break-even",
    }[kind] || kind;
  }

  function launchHistoryText(kind, configName, compact) {
    var record = matchingFinishedJob(kind, configName);
    if (!record) return compact ? "No prior session with this config." :
      "No prior " + launchKindLabel(kind) + " session with this config.";
    var prefix = compact ? "Last session" :
      "Last " + launchKindLabel(kind) + " with " + configName;
    return prefix + " took " + formatSeconds(record.elapsed_seconds) + ".";
  }

  function updateLaunchExpectations() {
    var configName = configSelect && configSelect.value;
    if (!configName) return;
    document.querySelectorAll(
      "[data-launch-history-kind], [data-launch-history]"
    ).forEach(function (element) {
      element.textContent = launchHistoryText(
        element.dataset.launchHistoryKind || element.dataset.launchHistory ||
          element.dataset.kind,
        configName, true
      );
    });
    // A template may place the history node either inside the existing
    // expectation strip or immediately beside the Start button.
    ["launch-history-expectation", "launch-expectation-history"].forEach(function (id) {
      var element = document.getElementById(id);
      if (element) {
        element.textContent = launchHistoryText(selectedKind(), configName, false);
      }
    });
  }
  window.updateLaunchExpectations = updateLaunchExpectations;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", updateLaunchExpectations);
  } else {
    updateLaunchExpectations();
  }

  // A launched analysis is one object with one home: a live card in the runs
  // panel that resolves in place into the finished run's card.

  var baseDocumentTitle = document.title;

  function setTitleProgress(job) {
    if (!job || job.status === "done" || job.status === "failed" ||
        job.status === "cancelled") {
      document.title = baseDocumentTitle;
      return;
    }
    var pct = job.progress_percent !== null && job.progress_percent !== undefined
      ? Math.round(job.progress_percent) + "%" : "…";
    document.title = "⏳ " + pct + " " + job.kind + " · SolarClean-DT";
  }

  function maybeNotify(title, body) {
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    if (!document.hidden) return; // the page itself already shows the state
    try { new Notification(title, { body: body }); } catch (e) { /* ignore */ }
  }

  function jobCardsContainer() {
    return document.getElementById("job-cards");
  }

  function addJobCard(job) {
    var container = jobCardsContainer();
    if (!container) return;
    container.hidden = false;
    var card = document.createElement("article");
    card.className = "job-card job-card-" + job.status;
    card.dataset.job = job.job_id;
    card.innerHTML =
      '<header class="job-card-head"><span class="run-kind"></span>' +
      '<span class="job-status"><span class="status status-queued">queued</span></span>' +
      '<span class="mono job-card-created"></span></header>' +
      '<strong class="job-card-config mono"></strong>' +
      '<div class="job-card-progress" role="progressbar" aria-label="Run progress" ' +
      'aria-valuemin="0" aria-valuemax="100">' +
      '<div class="progress-track"><div class="progress-fill" style="width: 0%"></div></div>' +
      '<span class="progress-label mono">–</span></div>' +
      '<div class="job-card-meta mono"><span class="job-elapsed">–</span>' +
      '<span class="job-eta">–</span></div>' +
      '<p class="job-card-result"></p>' +
      '<div class="run-actions"><button type="button" class="danger-quiet job-delete" ' +
      'data-job-id="' + job.job_id + '">Cancel &amp; remove</button></div>';
    card.querySelector(".run-kind").textContent = job.kind;
    card.querySelector(".job-card-created").textContent = job.created_at.slice(0, 19);
    card.querySelector(".job-card-config").textContent = job.config_name || "–";
    container.insertBefore(card, container.firstChild);
  }

  function updateJobCard(card, job) {
    card.className = "job-card job-card-" + job.status;
    var statusEl = card.querySelector(".job-status .status");
    if (statusEl) {
      statusEl.className = "status status-" + job.status;
      statusEl.textContent = job.status;
      if (job.detail) statusEl.dataset.pop = job.detail;
    }
    var progress = card.querySelector(".job-card-progress");
    if (progress) {
      var fill = progress.querySelector(".progress-fill");
      var label = progress.querySelector(".progress-label");
      if (job.progress_percent !== null && job.progress_percent !== undefined) {
        var pct = Math.round(job.progress_percent);
        progress.setAttribute("aria-valuenow", String(pct));
        // Update in place so the CSS width transition can animate the fill.
        if (fill) fill.style.width = pct + "%";
        if (label) label.textContent = pct + "%";
      } else {
        // No honest unit counts for this analysis kind: show no percentage.
        progress.removeAttribute("aria-valuenow");
        if (fill) fill.style.width = "0%";
        if (label) label.textContent = "–";
      }
    }
    var elapsed = card.querySelector(".job-elapsed");
    if (elapsed) elapsed.textContent = formatSeconds(job.elapsed_seconds);
    var eta = card.querySelector(".job-eta");
    if (eta) {
      eta.textContent =
        job.eta_seconds !== null && job.eta_seconds !== undefined
          ? "~" + formatSeconds(job.eta_seconds) + " left"
          : "–";
    }
    var deleteBtn = card.querySelector(".job-delete");
    if (deleteBtn && job.status !== "queued" && job.status !== "running") {
      deleteBtn.textContent = "Dismiss";
    }
    setTitleProgress(job);
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

  function removeJobCard(card) {
    card.remove();
    var container = jobCardsContainer();
    if (container && !container.querySelector(".job-card")) container.hidden = true;
    document.title = baseDocumentTitle;
  }

  function promoteCompletedJob(card, attemptsRemaining) {
    refreshCompletedRuns().then(function (refreshed) {
      if (refreshed) {
        removeJobCard(card);
      } else if (attemptsRemaining > 1) {
        setTimeout(function () {
          promoteCompletedJob(card, attemptsRemaining - 1);
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
          var card = document.querySelector('[data-job="' + jobId + '"]');
          if (!card) { clearInterval(timer); return; }
          updateJobCard(card, job);
          if (job.status === "done" && job.run_id) {
            var result = card.querySelector(".job-card-result");
            if (result) {
              result.innerHTML = '<a href="/run/' + job.run_id + '">' + job.run_id + "</a>";
            }
            clearInterval(timer);
            maybeNotify("SolarClean-DT: " + job.kind + " finished",
              "Run " + job.run_id + " is ready to read.");
            promoteCompletedJob(card, 3);
          } else if (job.status === "failed") {
            var failure = card.querySelector(".job-card-result");
            if (failure) {
              failure.textContent = job.error || "failed";
              failure.className = "job-card-result error-text";
            }
            clearInterval(timer);
            maybeNotify("SolarClean-DT: " + job.kind + " failed",
              job.error || "The session failed — details on the runs page.");
          } else if (job.status === "cancelled") {
            clearInterval(timer);
            document.title = baseDocumentTitle;
          }
        })
        .catch(function () {
          consecutiveFailures += 1;
          if (consecutiveFailures >= 5) clearInterval(timer);
        });
    }, 2000);
  }

  // Resume polling for jobs that were still running when the page loaded.
  document.querySelectorAll(".job-card[data-job]").forEach(function (card) {
    var status = card.querySelector(".job-status").textContent.trim();
    if (status === "queued" || status === "running") pollJob(card.dataset.job);
  });

  // Dismiss / cancel a session card (event delegation so new cards work too).
  var jobCardsHost = jobCardsContainer();
  if (jobCardsHost) {
    jobCardsHost.addEventListener("click", function (event) {
      var button = event.target.closest(".job-delete");
      if (!button) return;
      var jobId = button.dataset.jobId;
      button.disabled = true;
      fetch("/api/jobs/" + jobId, { method: "DELETE" })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          var card = document.querySelector('[data-job="' + jobId + '"]');
          if (card) removeJobCard(card);
        })
        .catch(function () { button.disabled = false; });
    });
  }

  // --- deleting completed runs ---------------------------------------
  // Destructive: removes the run directory (exports included). Single deletes
  // arm in place ("Really delete?") instead of a blocking native confirm;
  // bulk deletes go through an explicit dialog stating the count.

  function pruneStudyHeaders() {
    document.querySelectorAll("#runs-table .study-group").forEach(function (group) {
      if (!group.querySelector(".run-card")) group.remove();
    });
  }

  function deleteRuns(runIds, errorEl) {
    if (errorEl) errorEl.textContent = "";
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
          pruneStudyHeaders();
          applyRunFilter();
        })
        .catch(function (error) { if (errorEl) errorEl.textContent = error.message; });
    });
  }

  // Two-step in-place confirmation: first click arms the button, second click
  // (within a few seconds) executes. Anywhere-else clicks or the timeout
  // disarm it.
  function armDangerButton(button, label, onConfirm) {
    if (button.dataset.armed === "true") {
      clearTimeout(button.$armTimer);
      button.dataset.armed = "";
      button.classList.remove("armed");
      button.textContent = button.dataset.armLabel || label;
      onConfirm();
      return;
    }
    button.dataset.armed = "true";
    button.dataset.armLabel = label;
    button.classList.add("armed");
    button.textContent = "Really delete?";
    button.$armTimer = setTimeout(function () {
      button.dataset.armed = "";
      button.classList.remove("armed");
      button.textContent = label;
    }, 4000);
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

  // Every fragment is self-contained. If pagination splits one study across
  // two pages, fold the first incoming grid into the last existing group.
  function appendRunGroups(fragment) {
    var incomingGroups = Array.from(fragment.querySelectorAll(".study-group"));
    if (!incomingGroups.length) {
      runsTable.appendChild(fragment);
      return;
    }
    incomingGroups.forEach(function (group) {
      var existingGroups = runsTable.querySelectorAll(".study-group");
      var lastGroup = existingGroups.length ? existingGroups[existingGroups.length - 1] : null;
      if (lastGroup && lastGroup.dataset.study === group.dataset.study) {
        var targetGrid = lastGroup.querySelector(".study-run-grid");
        if (targetGrid) {
          group.querySelectorAll(".run-card").forEach(function (card) {
            targetGrid.appendChild(card);
          });
          return;
        }
      }
      runsTable.appendChild(group);
    });
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
        appendRunGroups(template.content);
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
    // The contextual action bar follows the selection: it appears near where
    // the user is clicking instead of asking them to travel back to a toolbar.
    var selectionBar = document.getElementById("selection-bar");
    if (selectionBar) selectionBar.hidden = selectedCount === 0;
    var selectionCount = document.getElementById("selection-count");
    if (selectionCount) {
      selectionCount.textContent = selectedCount + " selected";
    }
    var selectAllButton = document.getElementById("select-all-runs");
    if (selectAllButton) {
      var allSelected = !archiveHasMore() && checkboxes.length > 0 &&
        selectedCount === checkboxes.length;
      selectAllButton.disabled = checkboxes.length === 0 || selectEverything;
      selectAllButton.textContent = selectEverything ? "Loading all runs…" :
        allSelected ? "Clear matching selection" : "Select all matching runs";
      selectAllButton.setAttribute("aria-pressed", allSelected ? "true" : "false");
    }
  }

  // Client-side archive filter. Cards are only hidden/shown — nothing is
  // fetched or recomputed; the full archive is pulled in first so a search
  // covers every stored run, not just the loaded pages.
  function applyRunFilter() {
    var textInput = document.getElementById("run-filter-text");
    var kindSelect2 = document.getElementById("run-filter-kind");
    var statusSelect = document.getElementById("run-filter-status-code");
    var provenanceSelect = document.getElementById("run-filter-provenance");
    if (!runsTable) return;
    var query = ((textInput && textInput.value) || "").trim().toLowerCase();
    var kind = (kindSelect2 && kindSelect2.value) || "";
    var statusCode = (statusSelect && statusSelect.value) || "";
    var provenance = (provenanceSelect && provenanceSelect.value) || "";
    var filterActive = Boolean(query || kind || statusCode || provenance);
    if (filterActive && archiveHasMore()) {
      setArchiveStatus("Loading the full archive to search it…");
      loadAllRunPages().then(applyRunFilter);
      return;
    }
    var cards = Array.from(runsTable.querySelectorAll(".run-card"));
    var shown = 0;
    cards.forEach(function (card) {
      var searchableText = (card.textContent + " " + (card.dataset.search || "")).toLowerCase();
      var matches = (!kind || card.dataset.kind === kind) &&
        (!statusCode || card.dataset.status === statusCode) &&
        (!provenance || card.dataset.provenance === provenance) &&
        (!query || searchableText.indexOf(query) !== -1);
      card.hidden = !matches;
      if (matches) {
        shown += 1;
      } else {
        // A hidden card must not stay silently selected for bulk delete.
        var checkbox = card.querySelector(".run-select");
        if (checkbox) checkbox.checked = false;
      }
    });
    // Hide the entire study unit when none of its own cards match.
    runsTable.querySelectorAll(".study-group").forEach(function (group) {
      group.hidden = !group.querySelector(".run-card:not([hidden])");
    });
    var status = document.getElementById("run-filter-status");
    if (status) {
      var hiddenTechnical = provenance === "study" ? cards.filter(function (card) {
        return card.dataset.provenance === "test";
      }).length : 0;
      if (hiddenTechnical && shown === 0) {
        status.textContent = hiddenTechnical + " technical/test runs hidden - " +
          "change Run source to include them.";
      } else if (hiddenTechnical) {
        status.textContent = shown + " study runs shown; " + hiddenTechnical +
          " technical/test runs hidden.";
      } else if (filterActive) {
        status.textContent = shown ? shown + " of " + cards.length + " runs match" :
          "No runs match these filters.";
      } else {
        status.textContent = "";
      }
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
      if (button) {
        armDangerButton(button, "Delete", function () {
          deleteRuns([button.dataset.runId], runsError);
        });
      }
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
    var runFilterStatus = document.getElementById("run-filter-status-code");
    var runFilterProvenance = document.getElementById("run-filter-provenance");
    if (runFilterText) runFilterText.addEventListener("input", applyRunFilter);
    if (runFilterKind) runFilterKind.addEventListener("change", applyRunFilter);
    if (runFilterStatus) runFilterStatus.addEventListener("change", applyRunFilter);
    if (runFilterProvenance) runFilterProvenance.addEventListener("change", applyRunFilter);
    var bulkButton = document.getElementById("delete-selected-runs");
    var bulkDialog = document.getElementById("bulk-delete-dialog");
    if (bulkButton && bulkDialog) {
      bulkButton.addEventListener("click", function () {
        var selected = Array.from(document.querySelectorAll(".run-select:checked"))
          .map(function (box) { return box.value; });
        if (!selected.length) return;
        var text = document.getElementById("bulk-delete-text");
        if (text) {
          text.textContent = selected.length === 1
            ? "Permanently delete run " + selected[0] + "?"
            : "Permanently delete " + selected.length + " selected runs?";
        }
        bulkDialog.showModal();
      });
      var bulkConfirm = document.getElementById("bulk-delete-confirm");
      if (bulkConfirm) {
        bulkConfirm.addEventListener("click", function () {
          var selected = Array.from(document.querySelectorAll(".run-select:checked"))
            .map(function (box) { return box.value; });
          bulkDialog.close();
          if (selected.length) deleteRuns(selected, runsError);
        });
      }
      var bulkCancel = document.getElementById("bulk-delete-cancel");
      if (bulkCancel) {
        bulkCancel.addEventListener("click", function () { bulkDialog.close(); });
      }
    }
    var clearSelectionButton = document.getElementById("clear-selection");
    if (clearSelectionButton) {
      clearSelectionButton.addEventListener("click", function () {
        document.querySelectorAll(".run-select:checked").forEach(function (box) {
          box.checked = false;
        });
        selectEverything = false;
        updateBulkDeleteState();
      });
    }
    var compareButton = document.getElementById("compare-selected-runs");
    if (compareButton) {
      compareButton.addEventListener("click", function () {
        var selected = Array.from(document.querySelectorAll(".run-select:checked"))
          .map(function (box) { return box.value; });
        if (selected.length === 2) {
          window.location.href = "/compare-runs?a=" + encodeURIComponent(selected[0]) +
            "&b=" + encodeURIComponent(selected[1]);
        }
      });
    }

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
    applyRunFilter();
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

  // --- artifact preview drawer ----------------------------------------
  // Artifact names remain real download links. A normal click opens the
  // stored-file preview; modifier clicks and the drawer's download action
  // retain the browser's native download/open behaviour.

  var artifactDrawerReturnFocus = null;

  function currentRunId() {
    if (window.solarcleanRunId) return String(window.solarcleanRunId);
    var runTagged = document.querySelector("[data-run-id]");
    if (runTagged && runTagged.dataset.runId) return runTagged.dataset.runId;
    var match = window.location.pathname.match(/^\/run\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function ensureArtifactDrawer() {
    var drawer = document.getElementById("artifact-preview-drawer");
    if (drawer) return drawer;
    drawer = document.createElement("dialog");
    drawer.id = "artifact-preview-drawer";
    drawer.className = "artifact-preview-drawer";
    drawer.setAttribute("aria-labelledby", "artifact-preview-title");
    drawer.setAttribute("aria-describedby", "artifact-preview-note");
    drawer.hidden = true;
    drawer.innerHTML =
      '<header class="artifact-preview-head"><div><span class="eyebrow">Stored artifact</span>' +
      '<h2 id="artifact-preview-title">Artifact preview</h2></div>' +
      '<button type="button" id="artifact-preview-close" class="artifact-preview-close" ' +
      'aria-label="Close artifact preview">×</button></header>' +
      '<div id="artifact-preview-content" class="artifact-preview-content"></div>' +
      '<footer class="artifact-preview-footer">' +
      '<p id="artifact-preview-note" class="hint artifact-preview-note"></p>' +
      '<a id="artifact-preview-download" class="artifact-preview-download" href="#" ' +
      'download>Download full artifact</a></footer>';
    document.body.appendChild(drawer);
    return drawer;
  }

  function artifactDrawerElement(drawer, id, selector) {
    return document.getElementById(id) || drawer.querySelector(selector);
  }

  function showArtifactDrawer(drawer, returnFocus) {
    artifactDrawerReturnFocus = returnFocus || document.activeElement;
    drawer.hidden = false;
    drawer.removeAttribute("aria-hidden");
    if (typeof drawer.showModal === "function" && !drawer.open) drawer.showModal();
    else {
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
    }
    document.body.classList.add("artifact-drawer-open");
    window.requestAnimationFrame(function () {
      var close = artifactDrawerElement(
        drawer, "artifact-preview-close", "[data-artifact-preview-close]"
      );
      if (close) close.focus();
    });
  }

  function closeArtifactDrawer() {
    var drawer = document.getElementById("artifact-preview-drawer");
    if (!drawer) return;
    var returnFocus = artifactDrawerReturnFocus;
    artifactDrawerReturnFocus = null;
    if (typeof drawer.close === "function" && drawer.open) drawer.close();
    drawer.classList.remove("open");
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("artifact-drawer-open");
    if (returnFocus && document.contains(returnFocus) &&
        typeof returnFocus.focus === "function") {
      window.requestAnimationFrame(function () { returnFocus.focus(); });
    }
  }

  function artifactDrawerFocusable(drawer) {
    return Array.from(drawer.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
      'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(function (element) { return !element.hidden; });
  }

  function previewKind(payload, artifactName) {
    var kind = String(
      payload.kind || payload.type || payload.preview_type || payload.format || ""
    ).toLowerCase();
    if (kind.indexOf("csv") >= 0) return "csv";
    if (kind.indexOf("json") >= 0) return "json";
    if (kind.indexOf("png") >= 0 || kind.indexOf("image") >= 0) return "png";
    if (kind.indexOf("text") >= 0 || kind.indexOf("yaml") >= 0 ||
        kind.indexOf("yml") >= 0) return "text";
    var extension = artifactName.split(".").pop().toLowerCase();
    if (extension === "csv") return "csv";
    if (extension === "json") return "json";
    if (extension === "png") return "png";
    return "text";
  }

  function renderArtifactTable(content, payload) {
    var header = payload.header || payload.columns || [];
    var rows = payload.rows || [];
    if (!Array.isArray(header) && rows.length && rows[0] &&
        typeof rows[0] === "object") {
      header = Object.keys(rows[0]);
    }
    var visibleRows = rows.slice(0, 50);
    var tableWrap = document.createElement("div");
    tableWrap.className = "artifact-preview-table-wrap";
    var table = document.createElement("table");
    table.className = "data-table small artifact-preview-table";
    if (header.length) {
      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      header.forEach(function (name) {
        var cell = document.createElement("th");
        cell.textContent = name;
        headRow.appendChild(cell);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);
    }
    var tbody = document.createElement("tbody");
    visibleRows.forEach(function (row) {
      var tableRow = document.createElement("tr");
      var values = Array.isArray(row) ? row : header.map(function (name) {
        return row && row[name];
      });
      values.forEach(function (value) {
        var cell = document.createElement("td");
        cell.textContent = value === null || value === undefined ? "" : String(value);
        tableRow.appendChild(cell);
      });
      tbody.appendChild(tableRow);
    });
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    content.appendChild(tableWrap);
    return visibleRows.length;
  }

  function renderArtifactPreview(drawer, payload, artifactName, downloadUrl) {
    var title = artifactDrawerElement(drawer, "artifact-preview-title", "h2");
    var content = artifactDrawerElement(
      drawer, "artifact-preview-content", ".artifact-preview-content"
    );
    var note = artifactDrawerElement(drawer, "artifact-preview-note", ".artifact-preview-note");
    var download = artifactDrawerElement(
      drawer, "artifact-preview-download", "[data-artifact-download]"
    );
    if (title) title.textContent = payload.name || artifactName;
    if (content) content.replaceChildren();
    if (content) content.setAttribute("aria-busy", "false");
    if (note) note.textContent = "";
    if (download) {
      download.href = payload.download_url || downloadUrl;
      download.hidden = false;
    }
    if (!content) return;

    var kind = previewKind(payload, artifactName);
    if (kind === "csv") {
      var shown = renderArtifactTable(content, payload);
      var total = payload.total_rows;
      if (total === undefined) total = payload.row_count;
      if (total === undefined) total = (payload.rows || []).length;
      if (note) {
        note.textContent = "Showing " + shown + " of " + total +
          " rows — download for full data.";
      }
    } else if (kind === "png") {
      var image = document.createElement("img");
      image.className = "artifact-preview-image";
      image.alt = "Stored artifact preview: " + artifactName;
      image.src = payload.url || payload.preview_url || downloadUrl;
      content.appendChild(image);
      if (note) note.textContent = "Inline preview of the stored PNG.";
    } else {
      var pre = document.createElement("pre");
      pre.className = "summary-pre artifact-preview-pre";
      var value = payload.content;
      if (value === undefined) value = payload.data;
      if (kind === "json") {
        if (typeof value === "string") {
          try { value = JSON.parse(value); } catch (error) { /* display original text */ }
        }
        pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      } else {
        pre.textContent = value === null || value === undefined ? "" : String(value);
      }
      content.appendChild(pre);
      if (note) note.textContent = "Stored file content — download for the original artifact.";
    }
  }

  function openArtifactPreview(runId, artifactName, downloadUrl, trigger) {
    var drawer = ensureArtifactDrawer();
    var content = artifactDrawerElement(
      drawer, "artifact-preview-content", ".artifact-preview-content"
    );
    var title = artifactDrawerElement(drawer, "artifact-preview-title", "h2");
    var note = artifactDrawerElement(drawer, "artifact-preview-note", ".artifact-preview-note");
    if (title) title.textContent = artifactName;
    if (content) content.textContent = "Loading stored artifact…";
    if (content) content.setAttribute("aria-busy", "true");
    if (note) note.textContent = "";
    showArtifactDrawer(drawer, trigger);
    fetch(
      "/api/runs/" + encodeURIComponent(runId) + "/artifact-preview/" +
      encodeURIComponent(artifactName)
    )
      .then(function (response) {
        if (!response.ok) {
          return response.json().catch(function () { return {}; }).then(function (payload) {
            throw new Error(payload.detail || ("HTTP " + response.status));
          });
        }
        return response.json();
      })
      .then(function (payload) {
        renderArtifactPreview(drawer, payload, artifactName, downloadUrl);
      })
      .catch(function (error) {
        if (content) {
          content.setAttribute("aria-busy", "false");
          content.textContent = "Preview unavailable: " + error.message;
        }
        var download = artifactDrawerElement(
          drawer, "artifact-preview-download", "[data-artifact-download]"
        );
        if (download) {
          download.href = downloadUrl;
          download.hidden = false;
        }
      });
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented) return;
    var close = event.target.closest("#artifact-preview-close, [data-artifact-preview-close]");
    if (close) {
      closeArtifactDrawer();
      return;
    }
    var link = event.target.closest(
      "#artifact-files a[href*='/artifact/'], [data-artifact-preview]"
    );
    if (link && link.matches(".artifact-download-link, [data-artifact-download-direct]")) {
      return;
    }
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey ||
        event.shiftKey || event.altKey) return;
    var href = link.href || link.dataset.downloadUrl || "";
    var pathMatch = href && new URL(href, window.location.href).pathname.match(
      /^\/api\/runs\/([^/]+)\/artifact\/(.+)$/
    );
    var runId = link.dataset.runId || (pathMatch && decodeURIComponent(pathMatch[1])) ||
      currentRunId();
    var artifactName = link.dataset.artifactName || link.dataset.artifactPreview ||
      (pathMatch && decodeURIComponent(pathMatch[2])) || link.textContent.trim();
    if (!runId || !artifactName) return;
    event.preventDefault();
    openArtifactPreview(runId, artifactName, href ||
      "/api/runs/" + encodeURIComponent(runId) + "/artifact/" +
      encodeURIComponent(artifactName), link);
  });
  document.addEventListener("keydown", function (event) {
    var drawer = document.getElementById("artifact-preview-drawer");
    var open = drawer && !drawer.hidden && (drawer.open || drawer.classList.contains("open"));
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeArtifactDrawer();
      return;
    }
    if (event.key !== "Tab") return;
    var focusable = artifactDrawerFocusable(drawer);
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

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
    var nameInput = document.getElementById("site-name");
    var latInput = document.getElementById("site-lat");
    var lonInput = document.getElementById("site-lon");
    var timezoneInput = document.getElementById("site-timezone");
    var marker = document.getElementById("site-map-marker");
    if (nameInput) nameInput.value = parseYamlTextScalar(editor.value, "name") || "";
    if (latInput) latInput.value = isNaN(lat) ? "" : lat;
    if (lonInput) lonInput.value = isNaN(lon) ? "" : lon;
    if (timezoneInput) timezoneInput.value = parseYamlScalar(editor.value, "timezone") || "";
    var startInput = document.getElementById("site-start-date");
    var endInput = document.getElementById("site-end-date");
    var start = parseYamlScalar(editor.value, "start");
    var end = parseYamlScalar(editor.value, "end");
    if (startInput && start) startInput.value = start.slice(0, 10);
    if (endInput && end) endInput.value = end.slice(0, 10);
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

  function parseYamlTextScalar(content, key) {
    var match = content.match(new RegExp("^\\s*" + key + ":\\s*(.*?)\\s*$", "m"));
    if (!match) return null;
    var value = match[1].trim();
    if (value.startsWith('"') && value.endsWith('"')) {
      try {
        return JSON.parse(value);
      } catch (_error) {
        // Leave malformed YAML text visible so validation can explain the error.
      }
    }
    return value.replace(/^['"]|['"]$/g, "");
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
    var nameInput = document.getElementById("site-name");
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
    syncSiteLocationFromEditor(editor);
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
      var payload = {
        content: editor.value,
        latitude: lat,
        longitude: lon,
        site_name: nameInput ? nameInput.value : null,
      };
      var startInput = document.getElementById("site-start-date");
      var endInput = document.getElementById("site-end-date");
      var startDate = startInput ? startInput.value : "";
      var endDate = endInput ? endInput.value : "";
      if ((startDate === "") !== (endDate === "")) {
        statusEl.textContent = "Set both period dates (or neither to keep the stored period).";
        return;
      }
      if (startDate && endDate) {
        if (endDate < startDate) {
          statusEl.textContent = "Period end must be on or after period start.";
          return;
        }
        payload.start_date = startDate;
        payload.end_date = endDate;
      }
      applyButton.disabled = true;
      statusEl.textContent = "Detecting the timezone and calculating local UTC offsets…";
      fetch("/api/configs/" + encodeURIComponent(editor.dataset.name) + "/apply-location", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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
          var editorDetails = document.getElementById("config-editor-details");
          if (editorDetails) editorDetails.open = true;
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
      var weatherDetail = state.weather_status.detail || "";
      if (state.weather_status.state === "fetch") {
        weatherDetail += (weatherDetail ? " - " : "") +
          "It will be fetched automatically when you run the study.";
      }
      setText("cockpit-weather-detail", weatherDetail);
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

  // --- parameter pickers ------------------------------------------------
  // Searchable grouped checklists over the registry catalog. The native
  // selects stay in the DOM as the state store (and no-JS fallback): every
  // picker interaction just toggles option.selected, so the launch code and
  // server contract are unchanged. Ranges come from the catalog the server
  // rendered — nothing is computed beyond drawing a tick at the central value.

  var _parameterGroupLabels = {
    soiling: "Soiling",
    seasonality: "Seasonality",
    dust_events: "Dust events",
    rainfall: "Rainfall",
    bird: "Bird activity",
    cv: "Computer vision",
    inspection: "Inspection",
    cleaning: "Cleaning",
    coating: "Coating",
    economics: "Economics",
  };

  function parameterHumanLabel(name) {
    var leaf = name.indexOf(".") >= 0 ? name.slice(name.indexOf(".") + 1) : name;
    return leaf.replace(/_/g, " ");
  }

  function parameterRangeBar(parameter) {
    var bar = document.createElement("span");
    bar.className = "param-range-bar";
    var low = Number(parameter.low);
    var high = Number(parameter.high);
    var central = Number(parameter.central);
    if (isFinite(low) && isFinite(high) && isFinite(central) && high > low) {
      var tick = document.createElement("span");
      tick.className = "param-range-tick";
      tick.style.left = Math.max(0, Math.min(100, (central - low) / (high - low) * 100)) + "%";
      bar.appendChild(tick);
    }
    return bar;
  }

  window.initParameterPickers = function (parameters) {
    if (!Array.isArray(parameters) || !parameters.length) return;
    document.querySelectorAll(".param-picker[data-picker-for]").forEach(function (picker) {
      var select = document.getElementById(picker.dataset.pickerFor);
      if (!select) return;
      var multi = picker.dataset.pickerMode !== "single";
      select.classList.add("param-native-hidden");
      picker.hidden = false;
      picker.replaceChildren();

      var head = document.createElement("div");
      head.className = "param-picker-head";
      var search = document.createElement("input");
      search.type = "search";
      search.placeholder = "Filter parameters…";
      search.setAttribute("aria-label", "Filter parameters");
      head.appendChild(search);
      var count = document.createElement("span");
      count.className = "param-picker-count mono";
      head.appendChild(count);
      var clear = null;
      var selectAll = null;
      if (multi) {
        selectAll = document.createElement("button");
        selectAll.type = "button";
        selectAll.className = "param-picker-action";
        selectAll.textContent = "Select all";
        selectAll.title = "Select the complete catalog for an exhaustive sweep";
        head.appendChild(selectAll);
        clear = document.createElement("button");
        clear.type = "button";
        clear.className = "param-picker-action param-picker-clear";
        clear.textContent = "Clear";
        head.appendChild(clear);
      }
      picker.appendChild(head);

      var list = document.createElement("div");
      list.className = "param-picker-list";
      picker.appendChild(list);

      function selectedValues() {
        return new Set(Array.from(select.selectedOptions).map(function (option) {
          return option.value;
        }));
      }

      function updateCount() {
        if (multi) {
          var selected = selectedValues().size;
          count.textContent = selected ? selected + " selected" : "none selected";
          if (clear) clear.hidden = !selected;
          if (selectAll) selectAll.hidden = selected === select.options.length;
        } else {
          count.textContent = "";
        }
      }

      var chosen = selectedValues();
      var groups = {};
      parameters.forEach(function (parameter) {
        var groupKey = parameter.name.indexOf(".") >= 0
          ? parameter.name.slice(0, parameter.name.indexOf("."))
          : "other";
        (groups[groupKey] = groups[groupKey] || []).push(parameter);
      });

      Object.keys(groups).forEach(function (groupKey) {
        var heading = document.createElement("span");
        heading.className = "param-group-label";
        heading.textContent = _parameterGroupLabels[groupKey] || groupKey;
        list.appendChild(heading);
        groups[groupKey].forEach(function (parameter) {
          var row = document.createElement("label");
          row.className = "param-row";
          row.dataset.search = (parameter.name + " " + parameterHumanLabel(parameter.name) +
            " " + parameter.unit).toLowerCase();
          var input = document.createElement("input");
          input.type = multi ? "checkbox" : "radio";
          if (!multi) input.name = "picker-" + select.id;
          input.value = parameter.name;
          input.checked = chosen.has(parameter.name);
          input.addEventListener("change", function () {
            Array.from(select.options).forEach(function (option) {
              if (multi) {
                if (option.value === parameter.name) option.selected = input.checked;
              } else {
                option.selected = option.value === input.value;
              }
            });
            updateCount();
            select.dispatchEvent(new Event("change", { bubbles: true }));
          });
          var body = document.createElement("span");
          body.className = "param-row-body";
          var title = document.createElement("span");
          title.className = "param-row-title";
          title.textContent = parameterHumanLabel(parameter.name);
          var key = document.createElement("span");
          key.className = "param-row-key mono";
          key.textContent = parameter.name;
          var range = document.createElement("span");
          range.className = "param-row-range";
          range.appendChild(parameterRangeBar(parameter));
          var rangeText = document.createElement("span");
          rangeText.className = "param-row-range-text mono";
          rangeText.textContent = parameter.low + " – " + parameter.central + " – " +
            parameter.high + " " + parameter.unit;
          range.appendChild(rangeText);
          body.append(title, key, range);
          row.append(input, body);
          list.appendChild(row);
        });
      });

      search.addEventListener("input", function () {
        var query = search.value.trim().toLowerCase();
        list.querySelectorAll(".param-row").forEach(function (row) {
          row.hidden = Boolean(query) && row.dataset.search.indexOf(query) === -1;
        });
        list.querySelectorAll(".param-group-label").forEach(function (heading) {
          var sibling = heading.nextElementSibling;
          var visible = false;
          while (sibling && !sibling.classList.contains("param-group-label")) {
            if (sibling.classList.contains("param-row") && !sibling.hidden) visible = true;
            sibling = sibling.nextElementSibling;
          }
          heading.hidden = !visible;
        });
      });

      if (clear) {
        clear.addEventListener("click", function () {
          Array.from(select.options).forEach(function (option) { option.selected = false; });
          list.querySelectorAll("input").forEach(function (input) { input.checked = false; });
          updateCount();
          select.dispatchEvent(new Event("change", { bubbles: true }));
        });
      }
      if (selectAll) {
        selectAll.addEventListener("click", function () {
          Array.from(select.options).forEach(function (option) { option.selected = true; });
          list.querySelectorAll("input").forEach(function (input) { input.checked = true; });
          updateCount();
          select.dispatchEvent(new Event("change", { bubbles: true }));
        });
      }
      updateCount();
    });
  };

  // --- section-nav scroll spy -------------------------------------------
  // "You are here" for long record pages: the sticky jump nav highlights the
  // section currently under the reading line.

  var sectionNav = document.querySelector(".section-nav");
  if (sectionNav) {
    var navLinks = Array.from(sectionNav.querySelectorAll('a[href^="#"]'));
    var navSections = navLinks
      .map(function (link) { return document.getElementById(link.getAttribute("href").slice(1)); })
      .filter(Boolean);
    var spyScheduled = false;
    var updateSpy = function () {
      spyScheduled = false;
      var current = null;
      navSections.forEach(function (section) {
        if (section.getBoundingClientRect().top <= 96) current = section;
      });
      navLinks.forEach(function (link) {
        var active = current && link.getAttribute("href") === "#" + current.id;
        link.classList.toggle("nav-current", Boolean(active));
        if (active) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
    };
    window.addEventListener("scroll", function () {
      if (spyScheduled) return;
      spyScheduled = true;
      requestAnimationFrame(updateSpy);
    }, { passive: true });
    updateSpy();
  }

  // --- humidity / dew-point simulator ----------------------------------
  // Inputs go to a small application endpoint backed by the same coating
  // domain functions as annual runs. JavaScript only renders that response.

  var dewSimulator = document.getElementById("dew-simulator");
  if (dewSimulator) {
    var dewControls = document.getElementById("dew-simulator-controls");
    var humidityInput = document.getElementById("dew-relative-humidity");
    var temperatureInput = document.getElementById("dew-air-temperature");
    var windInput = document.getElementById("dew-wind-speed");
    var humidityIndicator = document.getElementById("humidity-indicator");
    var dewOutput = document.getElementById("dew-simulator-output");
    var dewTimer = null;
    var dewRequest = null;

    function setDewText(id, value) {
      var element = document.getElementById(id);
      if (element) element.textContent = value;
    }

    function dewNumber(value, digits, suffix, signed) {
      if (typeof value !== "number" || !isFinite(value)) return "–";
      var prefix = signed && value > 0 ? "+" : "";
      return prefix + value.toFixed(digits) + suffix;
    }

    function updateDewInputLabels() {
      setDewText("dew-relative-humidity-value", Number(humidityInput.value).toFixed(0) + "%");
      setDewText("dew-air-temperature-value", Number(temperatureInput.value).toFixed(0) + " °C");
      setDewText("dew-wind-speed-value", Number(windInput.value).toFixed(1) + " m/s");
      setDewText("humidity-current-label", "Current RH " + Number(humidityInput.value).toFixed(0) + "%");
      if (humidityIndicator) {
        var span = Number(humidityInput.max) - Number(humidityInput.min);
        var level = span > 0 ?
          (Number(humidityInput.value) - Number(humidityInput.min)) / span * 100 : 0;
        humidityIndicator.style.setProperty("--humidity-level", level.toFixed(2) + "%");
      }
    }

    function renderDewResult(payload) {
      dewOutput.setAttribute("aria-busy", "false");
      var status = document.getElementById("dew-status");
      status.className = "dew-status " + (
        payload.harvest_active ? "dew-status-active" :
          payload.dew_eligible ? "dew-status-forming" : "dew-status-dry"
      );
      status.textContent = payload.harvest_active ? "HARVESTING DEW" :
        payload.dew_eligible ? "DEW FORMING · NOT COLLECTED" : "DRY";
      setDewText("dew-status-message", payload.status_message);
      setDewText(
        "dew-input-summary",
        Number(payload.relative_humidity_pct).toFixed(0) + "% RH · " +
        Number(payload.air_temperature_c).toFixed(0) + " °C · " +
        Number(payload.wind_speed_m_s).toFixed(1) + " m/s"
      );
      setDewText("dew-point-value", dewNumber(payload.dew_point_c, 1, " °C", false));
      setDewText(
        "dew-surface-value",
        dewNumber(payload.coated_surface_temperature_c, 1, " °C", false)
      );
      setDewText("dew-margin-value", dewNumber(payload.dew_margin_c, 1, " °C", true));
      setDewText("dew-cooling-value", dewNumber(payload.cooling_delta_c, 1, " °C", false));
      setDewText(
        "dew-yield-value",
        dewNumber(payload.harvested_liters_per_m2_hour, 4, " L/m²/h", false)
      );
      setDewText(
        "dew-farm-yield-value",
        dewNumber(payload.whole_farm_harvested_liters_per_hour, 1, " L/h", false)
      );
      setDewText(
        "humidity-gate-label",
        "Collection gate " + Number(payload.minimum_relative_humidity_pct).toFixed(0) + "%"
      );
      if (humidityIndicator) {
        var humiditySpan = Number(humidityInput.max) - Number(humidityInput.min);
        var gate = humiditySpan > 0 ?
          (Number(payload.minimum_relative_humidity_pct) - Number(humidityInput.min)) /
          humiditySpan * 100 : 0;
        humidityIndicator.style.setProperty(
          "--humidity-threshold",
          Math.max(0, Math.min(100, gate)).toFixed(2) + "%"
        );
      }
    }

    function showDewError(message) {
      dewOutput.setAttribute("aria-busy", "false");
      var status = document.getElementById("dew-status");
      status.className = "dew-status dew-status-error";
      status.textContent = "UNAVAILABLE";
      setDewText("dew-status-message", message);
    }

    function requestDewSimulation() {
      if (dewRequest) dewRequest.abort();
      dewRequest = new AbortController();
      dewOutput.setAttribute("aria-busy", "true");
      var query = new URLSearchParams({
        relative_humidity_pct: humidityInput.value,
        air_temperature_c: temperatureInput.value,
        wind_speed_m_s: windInput.value,
      });
      fetch(dewSimulator.dataset.endpoint + "?" + query.toString(), {
        signal: dewRequest.signal,
        headers: { "Accept": "application/json" },
      })
        .then(function (response) {
          if (!response.ok) throw new Error("The coating model could not evaluate these inputs.");
          return response.json();
        })
        .then(renderDewResult)
        .catch(function (error) {
          if (error.name !== "AbortError") showDewError(error.message);
        });
    }

    function scheduleDewSimulation() {
      updateDewInputLabels();
      window.clearTimeout(dewTimer);
      dewTimer = window.setTimeout(requestDewSimulation, 120);
    }

    [humidityInput, temperatureInput, windInput].forEach(function (input) {
      input.addEventListener("input", scheduleDewSimulation);
    });
    dewControls.addEventListener("submit", function (event) { event.preventDefault(); });
    updateDewInputLabels();
    requestDewSimulation();
  }

  // --- command palette ----------------------------------------------------
  // Ctrl+K navigation for people who think in run ids and sites. The index is
  // the same stored listing the run cards use; actions are plain client-side
  // toggles and links.

  var palette = document.getElementById("command-palette");
  if (palette && typeof palette.showModal === "function") {
    var paletteInput = document.getElementById("palette-input");
    var paletteResults = document.getElementById("palette-results");
    var paletteIndex = null;
    var paletteActive = 0;

    var paletteActions = [
      { label: "File a new analysis", hint: "home · launch form", href: "/#launch-form" },
      { label: "Open Default configuration", hint: "/config", href: "/config/default.yaml" },
      { label: "Toggle audit mode", hint: "source traces", run: function () {
        setAuditMode(!document.body.classList.contains("audit-mode"));
      } },
      { label: "Switch Daylight / Night shift", hint: "theme", run: function () {
        if (themeToggle) themeToggle.click();
      } },
    ];

    function paletteEntries() {
      var entries = paletteActions.map(function (action) {
        return {
          label: action.label,
          hint: action.hint,
          search: (action.label + " " + action.hint).toLowerCase(),
          href: action.href,
          run: action.run,
        };
      });
      ((paletteIndex && paletteIndex.runs) || []).forEach(function (run) {
        entries.push({
          label: (run.site || run.kind_label) + " — " + run.kind_label +
            (run.winner ? " · " + run.winner : ""),
          hint: run.created + " · " + run.run_id,
          search: (run.run_id + " " + run.kind_label + " " + (run.site || "") + " " +
            (run.winner || "")).toLowerCase(),
          href: "/run/" + run.run_id,
        });
      });
      return entries;
    }

    function renderPalette() {
      var query = paletteInput.value.trim().toLowerCase();
      var terms = query ? query.split(/\s+/) : [];
      var matches = paletteEntries().filter(function (entry) {
        return terms.every(function (term) { return entry.search.indexOf(term) !== -1; });
      }).slice(0, 12);
      paletteResults.replaceChildren();
      paletteActive = Math.min(paletteActive, Math.max(0, matches.length - 1));
      matches.forEach(function (entry, index) {
        var item = document.createElement("li");
        item.setAttribute("role", "option");
        item.className = index === paletteActive ? "palette-active" : "";
        var label = document.createElement("span");
        label.className = "palette-label";
        label.textContent = entry.label;
        var hint = document.createElement("span");
        hint.className = "palette-item-hint mono";
        hint.textContent = entry.hint || "";
        item.append(label, hint);
        item.addEventListener("click", function () { activatePaletteEntry(entry); });
        paletteResults.appendChild(item);
      });
      if (!matches.length) {
        var empty = document.createElement("li");
        empty.className = "palette-empty";
        empty.textContent = "No matching run or action.";
        paletteResults.appendChild(empty);
      }
      paletteResults.$matches = matches;
    }

    function activatePaletteEntry(entry) {
      palette.close();
      if (entry.run) entry.run();
      else if (entry.href) window.location.href = entry.href;
    }

    function openPalette() {
      paletteActive = 0;
      paletteInput.value = "";
      if (paletteIndex === null) {
        fetch("/api/command-index")
          .then(function (response) { return response.ok ? response.json() : null; })
          .then(function (payload) {
            paletteIndex = payload || { runs: [] };
            renderPalette();
          })
          .catch(function () { paletteIndex = { runs: [] }; renderPalette(); });
      }
      renderPalette();
      palette.showModal();
      paletteInput.focus();
    }

    paletteInput.addEventListener("input", function () {
      paletteActive = 0;
      renderPalette();
    });
    paletteInput.addEventListener("keydown", function (event) {
      var matches = paletteResults.$matches || [];
      if (event.key === "ArrowDown") {
        event.preventDefault();
        paletteActive = Math.min(paletteActive + 1, matches.length - 1);
        renderPalette();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        paletteActive = Math.max(paletteActive - 1, 0);
        renderPalette();
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (matches[paletteActive]) activatePaletteEntry(matches[paletteActive]);
      }
    });
    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && (event.key === "k" || event.key === "K")) {
        event.preventDefault();
        if (palette.open) palette.close();
        else openPalette();
      }
    });
    var paletteOpenButton = document.getElementById("palette-open");
    if (paletteOpenButton) paletteOpenButton.addEventListener("click", openPalette);
    palette.addEventListener("click", function (event) {
      if (event.target === palette) palette.close(); // backdrop click
    });
  }

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
  var hourlyDetailChart = null;
  var hourlyRequestKey = "";
  var explorerPayload = null;
  var explorerIndex = -1;
  var explorerLocked = false;
  var explorerScenario = "baseline";
  var explorerMetric = "energy";
  var explorerRange = null; // [firstIndex, lastIndex] when the scrubber zooms
  var explorerRenderFrame = null;

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
      layout: { padding: { top: 4, right: 6, bottom: 0, left: 0 } },
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            color: chartInk(),
            usePointStyle: true,
            pointStyleWidth: 13,
            boxHeight: 8,
            boxWidth: 13,
            padding: 14,
            font: { size: 10.5 },
          },
        },
        tooltip: {
          padding: 9,
          titleMarginBottom: 6,
          bodySpacing: 4,
          usePointStyle: true,
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

  // These charts live in deliberately fixed-height instrument frames. Letting
  // Chart.js preserve its default 2:1 aspect ratio while CSS also forces the
  // canvas to fill the frame stretches the backing bitmap and can start a
  // resize-observer feedback loop. Keep one owner for both dimensions.
  function stabilizeFixedHeightChart(options) {
    options.responsive = true;
    options.maintainAspectRatio = false;
    options.resizeDelay = 100;
    return options;
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
      Object.keys(chart.options.scales || {}).forEach(function (axis) {
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

  function fractionDisplay(value) {
    return finiteDisplay(value, 4);
  }

  function litersDisplay(value) {
    return finiteDisplay(value, 1) + " L";
  }

  function queueDisplay(value) {
    return finiteDisplay(value, 0);
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
      if (row) {
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
      }
      var operational = document.querySelector(
        '[data-selected-operational="' + scenario + '"]'
      ) || row;
      if (!operational) return;
      operational.hidden = explorerScenario !== "compare" && scenario !== explorerScenario;
      operational.querySelectorAll(
        '[data-selected-field="bird-loss"], [data-selected-field="bird_loss"], ' +
        '[data-selected-field="bird"]'
      ).forEach(function (field) {
        field.textContent = fractionDisplay(
          valueOnDate(explorerPayload.dailyBirdLoss, date, scenario)
        );
      });
      operational.querySelectorAll(
        '[data-selected-field="collected-water"], [data-selected-field="collected_water"], ' +
        '[data-selected-field="water"]'
      ).forEach(function (field) {
        field.textContent = litersDisplay(
          valueOnDate(explorerPayload.dailyCollectedWater, date, scenario)
        );
      });
      operational.querySelectorAll(
        '[data-selected-field="queue-length"], [data-selected-field="queue_length"], ' +
        '[data-selected-field="queue"]'
      ).forEach(function (field) {
        field.textContent = queueDisplay(
          valueOnDate(explorerPayload.dailyQueue, date, scenario)
        );
      });
    });

    var reference = valueOnDate(explorerPayload.dailyCleanReference, date);
    var metricSpec = explorerMetricSpec(explorerMetric);
    if (metricSpec && ["bird", "birdloss", "bird-loss", "water",
      "collected-water", "queue", "queue-length"].indexOf(explorerMetric) >= 0) {
      if (explorerScenario === "compare") {
        setExplorerText(
          "selected-day-summary",
          "Compare the stored " + metricSpec.summaryLabel +
          " for each scenario on this date."
        );
      } else {
        setExplorerText(
          "selected-day-summary",
          explorerScenario + " stored " + metricSpec.summaryLabel + " was " +
          metricSpec.format(valueOnDate(metricSpec.data, date, explorerScenario)) + "."
        );
      }
    } else if (explorerScenario === "compare") {
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

  function hourlyLabels(timestamps) {
    return timestamps.map(function (timestamp) {
      var text = String(timestamp);
      var match = text.match(/[T ](\d{2}:\d{2})/);
      return match ? match[1] : text;
    });
  }

  function ensureHourlyCanvas() {
    var canvas = document.getElementById("hourly-detail-chart");
    if (canvas) return canvas;
    var host = document.getElementById("hourly-detail");
    if (!host) return null;
    canvas = document.createElement("canvas");
    canvas.id = "hourly-detail-chart";
    canvas.height = 135;
    canvas.setAttribute("role", "img");
    canvas.setAttribute(
      "aria-label",
      "Stored hourly weather and clean-reference energy for the locked day"
    );
    canvas.dataset.auditSource = "weather_hourly.csv + clean_energy_hourly.csv";
    host.appendChild(canvas);
    return canvas;
  }

  function hourlyDataset(label, values, color, axis, dash) {
    return {
      label: label,
      data: values || [],
      borderColor: color,
      backgroundColor: "transparent",
      pointRadius: 0,
      borderWidth: 1.4,
      borderDash: dash || [],
      tension: 0,
      yAxisID: axis,
    };
  }

  function drawHourlyDetail(payload) {
    var canvas = ensureHourlyCanvas();
    if (!canvas || typeof Chart === "undefined") return;
    var datasets = [
      hourlyDataset("GHI (W/m²)", payload.ghi_w_m2, "#c07f0e", "yGhi"),
      hourlyDataset("Air temperature (°C)", payload.temp_air_c, "#a3453c", "yTemp"),
      hourlyDataset("Wind (m/s)", payload.wind_speed_m_s, "#2f7d5c", "yWind"),
      hourlyDataset("Relative humidity (%)", payload.relative_humidity_pct, "#2f7fa3", "yHumidity"),
      hourlyDataset(
        "Clean reference (kWh)", payload.clean_ac_energy_kwh,
        chartInk(), "yEnergy", [7, 4]
      ),
    ];
    var options = baseOptions("");
    options.maintainAspectRatio = false;
    options.interaction = { mode: "index", intersect: false };
    options.scales = {
      x: {
        ticks: { maxTicksLimit: 12, font: { size: 11 }, color: chartInk() },
        grid: { color: chartGrid() },
        title: { display: true, text: "Site-local hour", font: { size: 11 }, color: chartInk() },
      },
      yGhi: {
        type: "linear", position: "left", beginAtZero: true,
        title: { display: true, text: "GHI (W/m²)", font: { size: 11 }, color: chartInk() },
        ticks: { font: { size: 11 }, color: chartInk() },
        grid: { color: chartGrid() },
      },
      yEnergy: {
        type: "linear", position: "right", beginAtZero: true,
        title: {
          display: true, text: "Clean reference (kWh)",
          font: { size: 11 }, color: chartInk(),
        },
        ticks: { font: { size: 11 }, color: chartInk() },
        grid: { drawOnChartArea: false },
      },
      yTemp: { type: "linear", position: "right", display: false },
      yWind: { type: "linear", position: "right", display: false, beginAtZero: true },
      yHumidity: {
        type: "linear", position: "right", display: false, min: 0, max: 100,
      },
    };
    if (hourlyDetailChart) {
      hourlyDetailChart.data.labels = hourlyLabels(payload.timestamps || []);
      hourlyDetailChart.data.datasets = datasets;
      hourlyDetailChart.options = options;
      hourlyDetailChart.update();
    } else {
      hourlyDetailChart = registerChart(new Chart(canvas, {
        type: "line",
        data: { labels: hourlyLabels(payload.timestamps || []), datasets: datasets },
        options: options,
      }));
    }
    addChartDownloads();
  }

  function loadHourlyDetail(date) {
    var host = document.getElementById("hourly-detail");
    var status = document.getElementById("hourly-detail-status");
    var runId = currentRunId();
    if (!host || !runId) return;
    host.hidden = false;
    if (status) status.textContent = "Loading stored hourly weather + clean reference…";
    var requestKey = runId + "|" + date;
    hourlyRequestKey = requestKey;
    fetch(
      "/api/runs/" + encodeURIComponent(runId) + "/hourly/" + encodeURIComponent(date)
    )
      .then(function (response) {
        if (!response.ok) {
          return response.json().catch(function () { return {}; }).then(function (payload) {
            throw new Error(payload.detail || ("HTTP " + response.status));
          });
        }
        return response.json();
      })
      .then(function (payload) {
        if (hourlyRequestKey !== requestKey) return;
        drawHourlyDetail(payload);
        if (status) {
          status.textContent = "Stored hourly weather + clean reference · " +
            (payload.timestamps || []).length + " rows · no scenario hourly energy.";
        }
      })
      .catch(function (error) {
        if (hourlyRequestKey !== requestKey) return;
        if (status) status.textContent = "Hourly detail unavailable: " + error.message;
      });
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
    updateFollowHoverButton();

    // Pointer events can arrive much faster than the browser paints. Coalesce
    // the aligned-cursor and selected-day work into one render per frame so
    // hovering one track does not synchronously redraw every chart many times.
    if (explorerRenderFrame === null) {
      explorerRenderFrame = window.requestAnimationFrame(function () {
        explorerRenderFrame = null;
        explorerCharts.forEach(function (chart) {
          chart.$explorerIndex = explorerIndex;
          chart.draw();
        });
        renderSelectedDay();
      });
    }
    if (lockSelection) {
      loadHourlyDetail(explorerPayload.dailyEnergy.dates[nextIndex]);
    }
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

  function describeContextChart(canvas, label) {
    if (!canvas) return;
    if (!canvas.hasAttribute("role")) canvas.setAttribute("role", "img");
    if (!canvas.hasAttribute("aria-label")) canvas.setAttribute("aria-label", label);
    canvas.setAttribute("aria-describedby", "selected-day-summary");
  }

  function drawContextTracks(payload) {
    var dates = payload.dailyEnergy.dates;
    var weather = payload.dailyWeather;
    var ghiCanvas = document.getElementById("daily-ghi-chart");
    if (weather && ghiCanvas) {
      describeContextChart(
        ghiCanvas,
        "Daily GHI context chart aligned by date with the interactive daily explorer"
      );
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
      describeContextChart(
        temperatureCanvas,
        "Daily ambient and module temperature context chart aligned with the daily explorer"
      );
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
      describeContextChart(
        rainfallCanvas,
        "Daily rainfall context chart aligned by date with the interactive daily explorer"
      );
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

    var humidityCanvas = document.getElementById("daily-humidity-chart");
    if (humidityCanvas && payload.dailyHumidity) {
      describeContextChart(
        humidityCanvas,
        "Daily mean relative humidity context chart aligned with the daily explorer"
      );
      var humidityOptions = trackOptions(false);
      humidityOptions.scales.y.min = 0;
      humidityOptions.scales.y.max = 100;
      registerExplorerChart(new Chart(humidityCanvas, {
        type: "line",
        data: { labels: dates, datasets: [{
          label: "Daily mean relative humidity",
          data: payload.dailyHumidity.values,
          borderColor: "#2f7fa3",
          backgroundColor: "rgba(47, 127, 163, 0.12)",
          fill: true,
          pointRadius: 0,
          borderWidth: 1.25,
        }] },
        options: humidityOptions,
        plugins: [explorerCursorPlugin],
      }));
    }

    var eventCanvas = document.getElementById("daily-events-chart");
    if (eventCanvas) {
      describeContextChart(
        eventCanvas,
        "Stored rain, cleaning, inspection, coating, and contamination events aligned by date"
      );
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
      energyExplorerChart.data.datasets.forEach(function (dataset, index) {
        if (dataset._kind === "actual") {
          setExplorerDatasetVisible(
            index,
            scenario === "compare" || dataset._scenario === scenario
          );
        } else if (dataset._kind === "reference") {
          setExplorerDatasetVisible(index, explorerMetric === "energy");
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

  // One instrument, stored metrics only: the switcher redraws the same chart
  // from a different stored daily column. Column selection only.
  function explorerMetricSpec(metric) {
    if (!explorerPayload) return null;
    var specs = {
      energy: {
        data: explorerPayload.dailyEnergy,
        yLabel: "AC energy (kWh/day)",
        format: energyDisplay,
        showReference: true,
      },
      loss: {
        data: explorerPayload.dailyLoss,
        yLabel: "Energy loss (kWh/day)",
        format: energyDisplay,
        showReference: false,
      },
      cleanliness: {
        data: explorerPayload.dailySoiling,
        yLabel: "Cleanliness (1 = clean)",
        format: function (value) { return finiteDisplay(value, 4); },
        showReference: false,
      },
      cumgain: {
        data: explorerPayload.dailyCumGain,
        yLabel: "Cumulative gain vs baseline (kWh)",
        format: energyDisplay,
        showReference: false,
      },
      bird: {
        data: explorerPayload.dailyBirdLoss,
        yLabel: "Bird-dropping loss fraction",
        format: fractionDisplay,
        summaryLabel: "bird-dropping loss fraction",
        showReference: false,
      },
      birdloss: {
        data: explorerPayload.dailyBirdLoss,
        yLabel: "Bird-dropping loss fraction",
        format: fractionDisplay,
        summaryLabel: "bird-dropping loss fraction",
        showReference: false,
      },
      "bird-loss": {
        data: explorerPayload.dailyBirdLoss,
        yLabel: "Bird-dropping loss fraction",
        format: fractionDisplay,
        summaryLabel: "bird-dropping loss fraction",
        showReference: false,
      },
      water: {
        data: explorerPayload.dailyCollectedWater,
        yLabel: "Actually collected water (L/day)",
        format: litersDisplay,
        summaryLabel: "actually collected water",
        showReference: false,
      },
      "collected-water": {
        data: explorerPayload.dailyCollectedWater,
        yLabel: "Actually collected water (L/day)",
        format: litersDisplay,
        summaryLabel: "actually collected water",
        showReference: false,
      },
      queue: {
        data: explorerPayload.dailyQueue,
        yLabel: "Inspection queue length",
        format: queueDisplay,
        summaryLabel: "inspection queue length",
        showReference: false,
      },
      "queue-length": {
        data: explorerPayload.dailyQueue,
        yLabel: "Inspection queue length",
        format: queueDisplay,
        summaryLabel: "inspection queue length",
        showReference: false,
      },
    };
    var spec = specs[metric];
    return spec && spec.data && spec.data.series ? spec : null;
  }

  function setExplorerDatasetVisible(index, visible) {
    if (!energyExplorerChart || !energyExplorerChart.data.datasets[index]) return;
    // Keep both Chart.js visibility layers synchronized. Dataset.hidden alone
    // can be overridden by the controller's per-dataset metadata after another
    // filter or legend update, which let the clean reference leak into the
    // loss, cleanliness, and cumulative views.
    energyExplorerChart.data.datasets[index].hidden = !visible;
    if (typeof energyExplorerChart.setDatasetVisibility === "function") {
      energyExplorerChart.setDatasetVisibility(index, visible);
    } else if (typeof energyExplorerChart.getDatasetMeta === "function") {
      energyExplorerChart.getDatasetMeta(index).hidden = !visible;
    }
  }

  function applyExplorerMetric(metric) {
    var spec = explorerMetricSpec(metric);
    if (!spec || !energyExplorerChart) return;
    explorerMetric = metric;
    document.querySelectorAll("[data-energy-metric]").forEach(function (button) {
      var selected = button.getAttribute("data-energy-metric") === metric;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    energyExplorerChart.data.datasets.forEach(function (dataset, index) {
      if (dataset._kind === "actual") {
        dataset.data = spec.data.series[dataset._scenario] || [];
        setExplorerDatasetVisible(
          index,
          explorerScenario === "compare" || dataset._scenario === explorerScenario
        );
      } else if (dataset._kind === "reference") {
        setExplorerDatasetVisible(index, spec.showReference);
      }
    });
    if (energyExplorerChart.options.scales.y.title) {
      energyExplorerChart.options.scales.y.title.text = spec.yLabel;
    }
    energyExplorerChart.$metricFormat = spec.format;
    energyExplorerChart.update();
    renderSelectedDay();
  }

  // The full-width fingerprint doubles as the explorer's scrubber: drag a
  // window to zoom every explorer chart to that date range, click to select a
  // day. Zooming only changes the visible axis range of already-drawn stored
  // values.
  function setExplorerRange(first, last) {
    explorerRange = first === null ? null : [first, last];
    explorerCharts.forEach(function (chart) {
      chart.options.scales.x.min = first === null ? undefined : first;
      chart.options.scales.x.max = first === null ? undefined : last;
      chart.update();
    });
    var reset = document.getElementById("scrubber-reset");
    if (reset) reset.hidden = explorerRange === null;
  }

  function initExplorerScrubber(dates) {
    var wrap = document.getElementById("explorer-scrubber");
    var canvas = wrap && wrap.querySelector("canvas.run-fingerprint");
    if (!wrap || !canvas) return;
    var windowEl = document.createElement("span");
    windowEl.className = "scrubber-window";
    windowEl.hidden = true;
    canvas.parentElement.appendChild(windowEl);

    function indexAt(clientX) {
      var rect = canvas.getBoundingClientRect();
      var ratio = (clientX - rect.left) / rect.width;
      return clamp(Math.round(ratio * (dates.length - 1)), 0, dates.length - 1);
    }
    function paintWindow(startIndex, endIndex) {
      var first = Math.min(startIndex, endIndex);
      var last = Math.max(startIndex, endIndex);
      windowEl.hidden = false;
      windowEl.style.left = (first / (dates.length - 1) * 100) + "%";
      windowEl.style.width = Math.max(0.5, (last - first) / (dates.length - 1) * 100) + "%";
    }

    var dragStart = null;
    canvas.style.touchAction = "none";
    canvas.addEventListener("pointerdown", function (event) {
      dragStart = indexAt(event.clientX);
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove", function (event) {
      if (dragStart === null) return;
      paintWindow(dragStart, indexAt(event.clientX));
    });
    canvas.addEventListener("pointerup", function (event) {
      if (dragStart === null) return;
      var end = indexAt(event.clientX);
      var first = Math.min(dragStart, end);
      var last = Math.max(dragStart, end);
      dragStart = null;
      if (last - first < 3) {
        // A click (or tiny drag) selects the day instead of zooming.
        windowEl.hidden = explorerRange === null;
        setExplorerIndex(end, true);
        return;
      }
      paintWindow(first, last);
      setExplorerRange(first, last);
    });
    canvas.addEventListener("pointercancel", function () { dragStart = null; });

    var reset = document.getElementById("scrubber-reset");
    if (reset) {
      reset.addEventListener("click", function () {
        windowEl.hidden = true;
        setExplorerRange(null, null);
      });
    }
  }

  function drawEnergyExplorer(payload) {
    var data = payload.dailyEnergy;
    var canvas = document.getElementById("daily-energy-chart");
    if (!data || !data.series || !canvas || typeof Chart === "undefined") return;
    explorerPayload = payload;
    var datasets = Object.keys(data.series).map(function (scenario) {
      return {
        label: scenario.charAt(0).toUpperCase() + scenario.slice(1),
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
        var format = energyExplorerChart && energyExplorerChart.$metricFormat
          ? energyExplorerChart.$metricFormat : energyDisplay;
        return context.dataset.label + ": " + format(context.parsed.y);
      },
    };
    energyExplorerChart = registerExplorerChart(new Chart(canvas, {
      type: "line",
      data: { labels: data.dates, datasets: datasets },
      options: options,
      plugins: [explorerCursorPlugin],
    }));
    energyExplorerChart.$metricFormat = energyDisplay;
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
    document.querySelectorAll("[data-energy-metric]").forEach(function (button) {
      button.addEventListener("click", function () {
        applyExplorerMetric(button.getAttribute("data-energy-metric"));
      });
    });
    var followButton = document.getElementById("follow-hover-button");
    if (followButton) {
      followButton.addEventListener("click", function () {
        explorerLocked = false;
        updateFollowHoverButton();
      });
    }
    initExplorerScrubber(data.dates);
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

  function firstChartCanvas(ids) {
    for (var index = 0; index < ids.length; index += 1) {
      var canvas = document.getElementById(ids[index]);
      if (canvas) return canvas;
    }
    return null;
  }

  function storedSeries(source) {
    if (!source) return {};
    if (source.series && typeof source.series === "object") return source.series;
    if (Array.isArray(source.values)) return { stored: source.values };
    if (Array.isArray(source)) return { stored: source };
    return {};
  }

  function storedDates(panel, sources) {
    if (panel && Array.isArray(panel.dates)) return panel.dates;
    for (var index = 0; index < sources.length; index += 1) {
      if (sources[index] && Array.isArray(sources[index].dates)) return sources[index].dates;
    }
    return [];
  }

  function seriesColor(seriesName, fallback) {
    return ["baseline", "reactive", "coating"].indexOf(seriesName) >= 0
      ? scenarioColor(seriesName) : fallback;
  }

  function appendStoredDatasets(target, source, label, color, dash, axis) {
    var series = storedSeries(source);
    Object.keys(series).forEach(function (seriesName) {
      var scenarioNamed = ["baseline", "reactive", "coating"].indexOf(seriesName) >= 0;
      target.push({
        label: (scenarioNamed ? strategyAxisLabel(seriesName) + " · " : "") + label,
        _scenario: scenarioNamed ? seriesName : null,
        data: series[seriesName],
        borderColor: seriesColor(seriesName, color),
        backgroundColor: "transparent",
        pointRadius: 0,
        borderWidth: 1.5,
        borderDash: dash || [],
        tension: 0,
        yAxisID: axis || "y",
      });
    });
  }

  function drawStoredLineChart(canvas, labels, datasets, yLabel, extraOptions) {
    if (!canvas || !datasets.length || typeof Chart === "undefined" ||
        canvas.dataset.chartBound) return null;
    canvas.dataset.chartBound = "true";
    var options = stabilizeFixedHeightChart(baseOptions(yLabel));
    if (extraOptions) extraOptions(options);
    return registerChart(new Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: options,
    }));
  }

  // Detection instruments display the stored daily extensions as-is. In
  // particular, no daily confusion counts are added into synthetic annual
  // totals here.
  function drawDetectionPerformance(panel) {
    if (!panel) return;
    var missed = panel.missed || panel.missedKwh || panel.missed_kwh ||
      panel.missed_energy_impact_kwh;
    var recovered = panel.recovered || panel.recoveredKwh || panel.recovered_kwh ||
      panel.recovered_loss_estimated_kwh;
    var queue = panel.queue || panel.queueLength || panel.queue_length;
    var backlog = panel.backlog || panel.backlogLength || panel.backlog_length;
    var cancelled = panel.weatherCancelled || panel.weather_cancelled ||
      panel.weather_cancelled_flight;
    var dates = storedDates(panel, [missed, recovered, queue, backlog, cancelled]);

    var energyDatasets = [];
    appendStoredDatasets(energyDatasets, missed, "Missed contamination impact (kWh)",
      "#a3453c", [5, 3]);
    appendStoredDatasets(energyDatasets, recovered, "Recovered loss (kWh)",
      "#2f7d5c", []);
    drawStoredLineChart(
      firstChartCanvas([
        "detection-energy-chart", "detection-performance-energy-chart",
        "detection-missed-recovered-chart",
      ]),
      dates, energyDatasets, "Stored daily energy impact (kWh)"
    );

    var queueDatasets = [];
    appendStoredDatasets(queueDatasets, queue, "Queue", "#c07f0e", []);
    appendStoredDatasets(queueDatasets, backlog, "Backlog", "#7b5aa6", [5, 3]);
    var cancellationSeries = storedSeries(cancelled);
    Object.keys(cancellationSeries).forEach(function (seriesName) {
      var scenarioNamed = ["baseline", "reactive", "coating"].indexOf(seriesName) >= 0;
      queueDatasets.push({
        label: (scenarioNamed ? strategyAxisLabel(seriesName) + " · " : "") +
          "Weather-cancelled flight",
        _scenario: scenarioNamed ? seriesName : null,
        data: cancellationSeries[seriesName].map(function (value) {
          var cancelledValue = value === true || value === 1 ||
            String(value).toLowerCase() === "true";
          return cancelledValue ? 1 : null;
        }),
        borderColor: "#2f7fa3",
        backgroundColor: "#2f7fa3",
        showLine: false,
        pointRadius: 4,
        pointStyle: "rectRot",
        yAxisID: "yCancel",
      });
    });
    drawStoredLineChart(
      firstChartCanvas([
        "detection-queue-chart", "detection-performance-queue-chart",
        "detection-queue-backlog-chart",
      ]),
      dates, queueDatasets, "Stored queue / backlog length", function (options) {
        options.scales.y.beginAtZero = true;
        options.scales.yCancel = {
          display: false, min: 0, max: 1, position: "right",
          grid: { drawOnChartArea: false },
        };
      }
    );
  }

  function flatStoredValues(source, preferredSeries) {
    var series = storedSeries(source);
    if (preferredSeries && Array.isArray(series[preferredSeries])) {
      return series[preferredSeries];
    }
    var names = Object.keys(series);
    return names.length ? series[names[0]] : [];
  }

  function drawCoatingServiceLife(panel) {
    if (!panel) return;
    var age = panel.age || panel.ageDays || panel.age_days;
    var effectiveness = panel.effectiveness || panel.effectivenessFraction ||
      panel.effectiveness_fraction;
    var optical = panel.opticalEffect || panel.optical_effect_kwh;
    var temperature = panel.temperatureEffect || panel.temperature_effect_kwh;
    var cleanliness = panel.cleanlinessEffect || panel.cleanliness_effect_kwh;
    var dewPoint = panel.dewPoint || panel.dew_point_c;
    var surface = panel.surfaceTemperature || panel.coated_surface_temperature_c;
    var water = panel.collectedWater || panel.actually_collected_water_liters;
    var dates = storedDates(panel, [
      age, effectiveness, optical, temperature, cleanliness, dewPoint, surface, water,
    ]);

    var ageValues = flatStoredValues(age, "coating");
    var effectivenessValues = flatStoredValues(effectiveness, "coating");
    var lifeCanvas = firstChartCanvas([
      "coating-effectiveness-chart", "coating-service-life-chart",
    ]);
    if (lifeCanvas && ageValues.length && effectivenessValues.length &&
        typeof Chart !== "undefined" && !lifeCanvas.dataset.chartBound) {
      lifeCanvas.dataset.chartBound = "true";
      var lifeOptions = stabilizeFixedHeightChart(baseOptions("Effectiveness"));
      lifeOptions.scales.x.type = "linear";
      lifeOptions.scales.x.beginAtZero = true;
      lifeOptions.scales.x.title = {
        display: true, text: "Stored coating age (days)",
        font: { size: 11 }, color: chartInk(),
      };
      lifeOptions.scales.x.ticks.precision = 0;
      // Keep near-100% traces readable without hiding a genuinely lower
      // stored value: suggestedMin yields to the data when it falls below 90%.
      lifeOptions.scales.y.suggestedMin = 0.9;
      lifeOptions.scales.y.max = 1;
      lifeOptions.scales.y.ticks.callback = function (value) {
        return Math.round(Number(value) * 100) + "%";
      };
      lifeOptions.plugins.tooltip.callbacks = {
        label: function (context) {
          return "Effectiveness: " + finiteDisplay(context.parsed.y * 100, 2) + "%";
        },
        title: function (items) {
          return items.length ? "Coating age " + finiteDisplay(items[0].parsed.x, 0) + " days" : "";
        },
      };
      registerChart(new Chart(lifeCanvas, {
        type: "line",
        data: {
          datasets: [{
            label: "Coating effectiveness",
            _scenario: "coating",
            data: effectivenessValues.map(function (value, index) {
              return { x: ageValues[index], y: value };
            }),
            borderColor: scenarioColor("coating"),
            backgroundColor: cssVar("--surface", "#fff"),
            pointRadius: effectivenessValues.length <= 31 ? 2.5 : 0,
            pointHoverRadius: 4,
            borderWidth: 1.8,
            tension: 0,
          }],
        },
        options: lifeOptions,
      }));
    }

    var effectDatasets = [];
    appendStoredDatasets(effectDatasets, optical, "Optical effect", "#7b5aa6", []);
    appendStoredDatasets(
      effectDatasets, temperature, "Temperature effect", "#a3453c", []
    );
    appendStoredDatasets(
      effectDatasets, cleanliness, "Cleanliness effect", "#2f7d5c", []
    );
    drawStoredLineChart(
      firstChartCanvas(["coating-effects-chart", "coating-energy-effects-chart"]),
      dates, effectDatasets, "Stored daily effect (kWh)"
    );

    var dewDatasets = [];
    appendStoredDatasets(dewDatasets, dewPoint, "Dew point (°C)", "#2f7fa3", [], "y");
    appendStoredDatasets(
      dewDatasets, surface, "Coated surface (°C)", "#a3453c", [], "y"
    );
    appendStoredDatasets(
      dewDatasets, water, "Actually collected water (L)", "#2f7d5c", [], "yWater"
    );
    drawStoredLineChart(
      firstChartCanvas(["coating-dew-margin-chart", "coating-dew-chart"]),
      dates, dewDatasets, "Stored nighttime temperature (°C)", function (options) {
        if (Object.keys(storedSeries(water)).length) {
          options.scales.yWater = {
            type: "linear", position: "right", beginAtZero: true,
            title: {
              display: true, text: "Collected water (L)",
              font: { size: 11 }, color: chartInk(),
            },
            ticks: { font: { size: 11 }, color: chartInk() },
            grid: { drawOnChartArea: false },
          };
        }
      }
    );
  }

  // Small extension hook for future display-only stored-series charts. A
  // payload entry supplies Chart.js datasets and labels; this helper only
  // applies the dashboard's common axes and typography.
  function drawGenericCharts(payload) {
    var charts = payload && (payload.genericCharts || payload.charts);
    if (!charts || typeof charts !== "object" || typeof Chart === "undefined") return;
    Object.keys(charts).forEach(function (key) {
      var spec = charts[key];
      if (!spec) return;
      var canvas = document.getElementById(spec.canvasId || spec.canvas_id || key);
      if (!canvas || canvas.dataset.chartBound || !Array.isArray(spec.datasets)) return;
      canvas.dataset.chartBound = "true";
      var options = baseOptions(spec.yLabel || spec.y_label || "");
      if (spec.xLabel || spec.x_label) {
        options.scales.x.title = {
          display: true, text: spec.xLabel || spec.x_label,
          font: { size: 11 }, color: chartInk(),
        };
      }
      var datasets = spec.datasets.map(function (dataset) {
        var copy = Object.assign({}, dataset);
        if (copy.scenario) {
          copy._scenario = copy.scenario;
          copy.borderColor = copy.borderColor || scenarioColor(copy.scenario);
          copy.backgroundColor = copy.backgroundColor || "transparent";
          copy.pointStyle = copy.pointStyle || strategyPointStyle(copy.scenario);
        }
        return copy;
      });
      registerChart(new Chart(canvas, {
        type: spec.type || "line",
        data: {
          labels: spec.labels || spec.dates || [],
          datasets: datasets,
        },
        options: options,
      }));
    });
  }

  // Offer a PNG export next to each standalone chart. The image is exactly
  // the rendered canvas on the theme's surface colour — no data is re-read.
  var _downloadableCharts = [
    "daily-energy-chart", "mc-trials-chart", "mc-win-chart",
    "mc-benefit-chart", "tornado-chart", "breakeven-chart",
    "detection-energy-chart", "detection-performance-energy-chart",
    "detection-missed-recovered-chart", "detection-queue-chart",
    "detection-performance-queue-chart", "detection-queue-backlog-chart",
    "coating-effectiveness-chart", "coating-service-life-chart",
    "coating-effects-chart", "coating-energy-effects-chart",
    "coating-dew-margin-chart", "coating-dew-chart", "hourly-detail-chart",
  ];
  function addChartDownloads() {
    _downloadableCharts.forEach(function (id) {
      var canvas = document.getElementById(id);
      if (!canvas || canvas.dataset.downloadBound) return;
      canvas.dataset.downloadBound = "true";
      var button = document.createElement("button");
      button.type = "button";
      button.className = "chart-download";
      button.textContent = "Export PNG";
      button.setAttribute("aria-label", "Export " + id.replaceAll("-", " ") + " as PNG");
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
      var host = canvas.closest(
        ".energy-main-chart, .record-chart-frame, .hourly-chart-frame"
      ) || canvas;
      host.insertAdjacentElement("afterend", button);
    });
  }

  // Called from the comparison template after Chart.js loads. Data comes
  // straight from the run's stored CSV artifacts via the server.
  window.drawComparisonCharts = function () {
    applyChartTypography();
    var payload = window.solarcleanCharts || {};
    payload.dailyBirdLoss = payload.dailyBirdLoss || payload.dailyBirdLossFraction;
    payload.dailyCollectedWater = payload.dailyCollectedWater || payload.dailyWaterCollected;
    payload.dailyQueue = payload.dailyQueue || payload.dailyQueueLength;
    initDustCalendars(payload);
    drawEnergyExplorer(payload);
    drawDetectionPerformance(payload.detectionPerformance || payload.detection || {
      missed: payload.dailyMissedEnergyImpact,
      recovered: payload.dailyRecoveredLoss,
      queue: payload.dailyQueue,
      backlog: payload.dailyBacklog,
      weatherCancelled: payload.dailyWeatherCancelled,
    });
    drawCoatingServiceLife(payload.coatingServiceLife || payload.coatingService || {
      age: payload.dailyCoatingAge,
      effectiveness: payload.dailyCoatingEffectiveness,
      opticalEffect: payload.dailyOpticalEffect,
      temperatureEffect: payload.dailyTemperatureEffect,
      cleanlinessEffect: payload.dailyCleanlinessEffect,
      dewPoint: payload.dailyCoatingDewPoint,
      surfaceTemperature: payload.dailyCoatedSurfaceTemperature,
      collectedWater: payload.dailyCollectedWater,
    });
    drawGenericCharts(payload);
    addChartDownloads();
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
