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
  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var root = document.documentElement;
      var next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("solarclean-theme", next); } catch (e) { /* ignore */ }
      restyleCharts();
    });
  }

  var kindSelect = document.getElementById("kind");
  if (kindSelect) {
    var showOptionsForKind = function () {
      document.querySelectorAll(".kind-opts").forEach(function (row) {
        row.hidden = row.dataset.kind !== kindSelect.value;
      });
    };
    kindSelect.addEventListener("change", showOptionsForKind);
    showOptionsForKind();
  }

  var configSelect = document.getElementById("config");
  var configLink = document.getElementById("config-link");
  if (configSelect && configLink) {
    var updateConfigLink = function () {
      configLink.href = "/config/" + encodeURIComponent(configSelect.value);
    };
    configSelect.addEventListener("change", updateConfigLink);
    updateConfigLink();
  }

  // --- launching runs -----------------------------------------------------

  var launchButton = document.getElementById("launch");
  if (launchButton) {
    launchButton.addEventListener("click", function () {
      var errorEl = document.getElementById("launch-error");
      errorEl.textContent = "";

      var body = { kind: kindSelect.value, config: configSelect.value };
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
        progressCell.innerHTML =
          '<div class="progress-track"><div class="progress-fill" style="width: ' + pct +
          '%"></div></div><span class="progress-label mono">' + pct + "%</span>";
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

  // The completed-runs table is server-rendered. When a job finishes, fetch
  // the page again and swap in the fresh rows so the new run appears without
  // a manual reload (Jinja stays the only place that renders run rows).
  function refreshCompletedRuns() {
    fetch("/")
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (!html) return;
        var doc = new DOMParser().parseFromString(html, "text/html");
        var freshBody = doc.querySelector("#runs-table tbody");
        var currentBody = document.querySelector("#runs-table tbody");
        if (freshBody && currentBody) {
          currentBody.innerHTML = freshBody.innerHTML;
          updateBulkDeleteState();
        } else if (freshBody && !currentBody) {
          // First completed run ever: the empty-state panel has no table to
          // swap into, so take the one-off full reload.
          window.location.reload();
        }
      })
      .catch(function () { /* transient fetch issue: next completion retries */ });
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
            refreshCompletedRuns();
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
          if (row) row.remove();
          var tbody = document.querySelector("#jobs-table tbody");
          if (tbody && tbody.children.length === 0) {
            document.getElementById("jobs-panel").hidden = true;
          }
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
          var row = document.querySelector('tr[data-run="' + runId + '"]');
          if (row) row.remove();
          updateBulkDeleteState();
        })
        .catch(function (error) { errorEl.textContent = error.message; });
    });
  }

  function updateBulkDeleteState() {
    var bulkButton = document.getElementById("delete-selected-runs");
    var selectedCount = document.querySelectorAll(".run-select:checked").length;
    if (bulkButton) bulkButton.disabled = selectedCount === 0;
    var compareButton = document.getElementById("compare-selected-runs");
    if (compareButton) compareButton.disabled = selectedCount !== 2;
  }

  var runsTable = document.getElementById("runs-table");
  if (runsTable) {
    var runsError = document.getElementById("runs-delete-error");
    runsTable.addEventListener("click", function (event) {
      var button = event.target.closest(".run-delete");
      if (button) deleteRuns([button.dataset.runId], runsError);
    });
    runsTable.addEventListener("change", function (event) {
      if (event.target.classList.contains("run-select")) updateBulkDeleteState();
    });
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
  }

  // --- site location picker --------------------------------------------
  // Presentation-only helper: it edits the site.latitude / site.longitude
  // lines of the YAML in the editor textarea. Whether those coordinates
  // matter is stated honestly from weather.provider — only nasa_power
  // fetches weather by location; fixture/csv weather ignores it.

  function parseYamlScalar(content, key) {
    var match = content.match(new RegExp("^\\s*" + key + ":\\s*([^\\s#]+)", "m"));
    return match ? match[1] : null;
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
        "all change with the location. Soiling/dust and cost calibration stay on the " +
        "Riyadh central-v2 assumption set.";
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
    if (!isNaN(initialLat)) latInput.value = initialLat;
    if (!isNaN(initialLon)) lonInput.value = initialLon;
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
        " — press \"Apply to config above\" to write it into the YAML.";
    });

    [latInput, lonInput].forEach(function (input) {
      input.addEventListener("input", function () {
        placeMarker(parseFloat(latInput.value), parseFloat(lonInput.value));
      });
    });

    document.getElementById("apply-location").addEventListener("click", function () {
      var lat = parseFloat(latInput.value);
      var lon = parseFloat(lonInput.value);
      if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        statusEl.textContent = "Latitude must be -90..90 and longitude -180..180.";
        return;
      }
      var content = editor.value;
      var latPattern = /^(\s*latitude:\s*).*$/m;
      var lonPattern = /^(\s*longitude:\s*).*$/m;
      if (!latPattern.test(content) || !lonPattern.test(content)) {
        statusEl.textContent =
          "Could not find latitude:/longitude: lines in the YAML — edit them manually.";
        return;
      }
      editor.value = content
        .replace(latPattern, "$1" + lat)
        .replace(lonPattern, "$1" + lon);
      placeMarker(lat, lon);
      updateProviderNote(editor.value);
      statusEl.textContent = "Updated site.latitude / site.longitude in the editor — " +
        "validate and save to keep it.";
    });
  };

  // --- site location picker --------------------------------------------
  // Presentation-only helper: it edits the site.latitude / site.longitude
  // lines of the YAML in the editor textarea. Whether those coordinates
  // matter is stated honestly from weather.provider — only nasa_power
  // fetches weather by location; fixture/csv weather ignores it.

  function parseYamlScalar(content, key) {
    var match = content.match(new RegExp("^\\s*" + key + ":\\s*([^\\s#]+)", "m"));
    return match ? match[1] : null;
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
        "all change with the location. Soiling/dust and cost calibration stay on the " +
        "Riyadh central-v2 assumption set.";
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
    if (!isNaN(initialLat)) latInput.value = initialLat;
    if (!isNaN(initialLon)) lonInput.value = initialLon;
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
        " — press \"Apply to config above\" to write it into the YAML.";
    });

    [latInput, lonInput].forEach(function (input) {
      input.addEventListener("input", function () {
        placeMarker(parseFloat(latInput.value), parseFloat(lonInput.value));
      });
    });

    document.getElementById("apply-location").addEventListener("click", function () {
      var lat = parseFloat(latInput.value);
      var lon = parseFloat(lonInput.value);
      if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        statusEl.textContent = "Latitude must be -90..90 and longitude -180..180.";
        return;
      }
      var content = editor.value;
      var latPattern = /^(\s*latitude:\s*).*$/m;
      var lonPattern = /^(\s*longitude:\s*).*$/m;
      if (!latPattern.test(content) || !lonPattern.test(content)) {
        statusEl.textContent =
          "Could not find latitude:/longitude: lines in the YAML — edit them manually.";
        return;
      }
      editor.value = content
        .replace(latPattern, "$1" + lat)
        .replace(lonPattern, "$1" + lon);
      placeMarker(lat, lon);
      updateProviderNote(editor.value);
      statusEl.textContent = "Updated site.latitude / site.longitude in the editor — " +
        "validate and save to keep it.";
    });
  };

  // --- charts ---------------------------------------------------------

  var liveCharts = [];

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function chartInk() { return cssVar("--muted", "#5b6770"); }
  function chartGrid() { return cssVar("--line", "#d4d9d6"); }
  function scenarioColor(scenario) {
    return cssVar("--chart-" + scenario, cssVar("--ink", "#333"));
  }

  function baseOptions(yLabel) {
    return {
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom", labels: { color: chartInk() } } },
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
        if (dataset._scenario) {
          var color = scenarioColor(dataset._scenario);
          dataset.borderColor = color;
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
        label: style && style.label ? style.label : scenario,
        _scenario: colorScenario,
        data: data.series[scenario],
        borderColor: scenarioColor(colorScenario),
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

  // Called from the comparison template after Chart.js loads. Data comes
  // straight from the run's stored CSV artifacts via the server.
  window.drawComparisonCharts = function () {
    var payload = window.solarcleanCharts || {};
    drawScenarioLines("daily-energy-chart", payload.dailyEnergy, "AC energy (kWh/day)");
    drawScenarioLines("daily-loss-chart", payload.dailyLoss, "Energy loss (kWh/day)");
    drawScenarioLines(
      "daily-soiling-chart", payload.dailySoiling, "Dust / contamination cleanliness (1 = clean)"
    );
    drawDewCementationLines(payload.dailyDew, payload.dailyCementation);
    drawScenarioLines(
      "daily-cumgain-chart", payload.dailyCumGain, "Cumulative gain vs baseline (kWh)"
    );

    var bars = payload.annualCostBars;
    var canvas = document.getElementById("annual-cost-chart");
    if (bars && canvas && typeof Chart !== "undefined") {
      var metricColors = ["#2f7d5c", "#8a5a10", "#a3453c", "#16405b"];
      registerChart(new Chart(canvas, {
        type: "bar",
        data: {
          labels: bars.scenarios,
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
    drawMonteCarloSummaryCharts(window.solarcleanMonteCarlo);
    drawMcTrialsChart(window.solarcleanMcTrials);
    drawTornadoChart(window.solarcleanTornado);
    drawBreakEvenChart(window.solarcleanBreakEven);
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
      return Number.isInteger(value) ? scenarios[value] : "";
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
          labels: scenarios,
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
          labels: scenarios,
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
