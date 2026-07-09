// Dashboard behaviour. Plain fetch + polling; no build step, no framework.
// Server does the work — this file only sends requests and updates the DOM.

(function () {
  "use strict";

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

  var editLink = document.getElementById("edit-config-link");
  if (editLink) {
    editLink.addEventListener("click", function (event) {
      event.preventDefault();
      var name = document.getElementById("config").value;
      window.location.href = "/config/" + encodeURIComponent(name);
    });
  }

  // --- launching runs -----------------------------------------------------

  var launchButton = document.getElementById("launch");
  if (launchButton) {
    launchButton.addEventListener("click", function () {
      var errorEl = document.getElementById("launch-error");
      errorEl.textContent = "";

      var body = {
        kind: kindSelect.value,
        config_name: document.getElementById("config").value,
      };
      if (body.kind === "monte-carlo") {
        body.trials = parseInt(document.getElementById("trials").value, 10) || 25;
        var seed = document.getElementById("base-seed").value;
        if (seed !== "") body.base_seed = parseInt(seed, 10);
      } else if (body.kind === "sensitivity-oneway") {
        body.steps = parseInt(document.getElementById("steps").value, 10) || 5;
        var params = document.getElementById("parameters").value.trim();
        if (params) body.parameters = params.split(",").map(function (p) { return p.trim(); });
      } else if (body.kind === "winner-map") {
        body.parameter_a = document.getElementById("parameter-a").value.trim();
        body.parameter_b = document.getElementById("parameter-b").value.trim();
        body.grid_steps = parseInt(document.getElementById("grid-steps").value, 10) || 5;
        if (!body.parameter_a || !body.parameter_b) {
          errorEl.textContent = "Winner map needs both parameter names.";
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

  function addJobRow(job) {
    var panel = document.getElementById("jobs-panel");
    panel.hidden = false;
    var tbody = document.querySelector("#jobs-table tbody");
    var row = document.createElement("tr");
    row.dataset.job = job.job_id;
    row.innerHTML =
      '<td class="mono">' + job.created_at.slice(0, 19) + "</td>" +
      "<td>" + job.kind + "</td>" +
      '<td class="mono">' + job.config_name + "</td>" +
      '<td><span class="status status-queued">queued</span></td>' +
      "<td></td>";
    tbody.insertBefore(row, tbody.firstChild);
  }

  function pollJob(jobId) {
    var timer = setInterval(function () {
      fetch("/api/jobs/" + jobId)
        .then(function (r) { return r.json(); })
        .then(function (job) {
          var row = document.querySelector('tr[data-job="' + jobId + '"]');
          if (!row) { clearInterval(timer); return; }
          var statusEl = row.children[3].firstChild;
          statusEl.className = "status status-" + job.status;
          statusEl.textContent = job.status;
          statusEl.title = job.detail || "";
          if (job.status === "done" && job.run_id) {
            row.children[4].innerHTML =
              '<a href="/run/' + job.run_id + '">' + job.run_id + "</a>";
            clearInterval(timer);
          } else if (job.status === "failed") {
            row.children[4].textContent = job.error || "failed";
            row.children[4].className = "error-text";
            clearInterval(timer);
          }
        })
        .catch(function () { clearInterval(timer); });
    }, 2000);
  }

  // Resume polling for jobs that were still running when the page loaded.
  document.querySelectorAll("#jobs-table tr[data-job]").forEach(function (row) {
    var status = row.children[3].textContent.trim();
    if (status === "queued" || status === "running") pollJob(row.dataset.job);
  });

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
          statusEl.textContent = "Valid. Saved as configs/" + result.saved_as +
            " — it now appears in the launch form.";
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
    document.getElementById("save-btn").addEventListener("click", function () {
      var name = document.getElementById("save-as").value.trim();
      var statusEl = document.getElementById("config-status");
      if (!name) {
        statusEl.className = "bad";
        statusEl.textContent = "Pick a file name to save as.";
        return;
      }
      validateConfig(name);
    });
  }

  // --- charts ---------------------------------------------------------

  // Called from the comparison template after Chart.js loads. Data comes
  // straight from scenario_daily_summary.csv via the server; nothing is
  // computed here.
  window.drawDailyEnergyChart = function () {
    var data = window.solarcleanDailyEnergy;
    var canvas = document.getElementById("daily-energy-chart");
    if (!data || !canvas || typeof Chart === "undefined") return;

    var colors = { baseline: "#5b6770", reactive: "#16405b", coating: "#7a5200" };
    var datasets = Object.keys(data.series).map(function (scenario) {
      return {
        label: scenario,
        data: data.series[scenario],
        borderColor: colors[scenario] || "#333",
        backgroundColor: "transparent",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0,
      };
    });

    new Chart(canvas, {
      type: "line",
      data: { labels: data.dates, datasets: datasets },
      options: {
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" } },
        scales: {
          x: { ticks: { maxTicksLimit: 14, font: { size: 11 } } },
          y: {
            title: { display: true, text: "AC energy (kWh/day)", font: { size: 11 } },
            ticks: { font: { size: 11 } },
          },
        },
      },
    });
  };
})();
