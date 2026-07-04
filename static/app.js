"use strict";

const $ = (id) => document.getElementById(id);

const urlInput = $("url");
const sourceBadge = $("source-badge");
const clearBtn = $("clear-btn");
const downloadBtn = $("download-btn");
const output = $("output");
const progressBlock = $("progress-block");
const progressMessage = $("progress-message");
const progressPercent = $("progress-percent");
const progressFill = $("progress-fill");
const skippedList = $("skipped-list");
const resultBlock = $("result-block");
const resultFilename = $("result-filename");
const saveBtn = $("save-btn");
const errorBlock = $("error-block");
const errorMessage = $("error-message");
const audioOptions = $("audio-options");
const videoOptions = $("video-options");

let mode = "audio";
let pollTimer = null;

/* ── Source detection badge ─────────────────────────────────────────── */
const SOURCES = [
  ["soundcloud.com", "SoundCloud"],
  ["spotify.com", "Spotify"],
  ["youtube.com", "YouTube"],
  ["youtu.be", "YouTube"],
];

function detectSource(url) {
  try {
    const host = new URL(url).hostname;
    const hit = SOURCES.find(([domain]) =>
      host === domain || host.endsWith("." + domain));
    return hit ? hit[1] : null;
  } catch {
    return null;
  }
}

urlInput.addEventListener("input", () => {
  const source = detectSource(urlInput.value.trim());
  sourceBadge.hidden = !source;
  sourceBadge.textContent = source || "";
  if (source === "Spotify" && mode === "video") setMode("audio");
  videoSegBtn().disabled = source === "Spotify";
});

/* ── Audio / video toggle ───────────────────────────────────────────── */
const segBtns = [...document.querySelectorAll(".seg-btn")];
const videoSegBtn = () => segBtns.find((b) => b.dataset.mode === "video");

function setMode(next) {
  mode = next;
  segBtns.forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  audioOptions.hidden = mode !== "audio";
  videoOptions.hidden = mode !== "video";
}
segBtns.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

/* Keep min ≤ max in the resolution range */
function clampResolutions(changed) {
  const min = $("min-res"), max = $("max-res");
  if (+min.value > +max.value) {
    (changed === "min" ? max : min).value =
      (changed === "min" ? min : max).value;
  }
}
$("min-res").addEventListener("change", () => clampResolutions("min"));
$("max-res").addEventListener("change", () => clampResolutions("max"));

/* ── Clear button: input AND output ─────────────────────────────────── */
clearBtn.addEventListener("click", () => {
  urlInput.value = "";
  sourceBadge.hidden = true;
  videoSegBtn().disabled = false;
  resetOutput();
  output.hidden = true;
  urlInput.focus();
});

function resetOutput() {
  clearTimeout(pollTimer);
  pollTimer = null;
  progressBlock.hidden = false;
  progressFill.style.width = "0%";
  progressFill.classList.remove("indeterminate");
  progressMessage.textContent = "Starting…";
  progressPercent.textContent = "";
  skippedList.hidden = true;
  skippedList.innerHTML = "";
  resultBlock.hidden = true;
  errorBlock.hidden = true;
  downloadBtn.disabled = false;
  downloadBtn.querySelector(".btn-label").textContent = "Download";
}

/* ── Download flow ──────────────────────────────────────────────────── */
downloadBtn.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  resetOutput();
  output.hidden = false;

  if (!url) return showError("Paste a link first.");
  if (!detectSource(url)) {
    return showError("That link isn't from SoundCloud, Spotify, or YouTube.");
  }

  downloadBtn.disabled = true;
  downloadBtn.querySelector(".btn-label").textContent = "Downloading…";

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        mode,
        audio_format: $("audio-format").value,
        min_res: +$("min-res").value,
        max_res: +$("max-res").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) return showError(data.error || "The server rejected the request.");
    poll(data.job_id);
  } catch {
    showError("Couldn't reach the server. Is it running?");
  }
});

function poll(jobId) {
  pollTimer = setTimeout(async () => {
    let job;
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      job = await res.json();
      if (!res.ok) return showError(job.error || "Lost track of the download.");
    } catch {
      return showError("Lost connection to the server.");
    }

    renderProgress(job);
    if (job.status === "done") return showResult(jobId, job.filename);
    if (job.status === "error") return showError(job.error);
    poll(jobId);
  }, 700);
}

function renderProgress(job) {
  progressMessage.textContent = job.message || "Working…";
  if (job.percent == null) {
    progressFill.classList.add("indeterminate");
    progressPercent.textContent = "";
  } else {
    progressFill.classList.remove("indeterminate");
    progressFill.style.width = `${job.percent}%`;
    progressPercent.textContent = `${Math.round(job.percent)}%`;
  }
  const skipped = job.skipped || [];
  if (skipped.length) {
    skippedList.hidden = false;
    skippedList.innerHTML = "";
    for (const item of skipped) {
      const li = document.createElement("li");
      li.textContent = `Skipped: ${item}`;
      skippedList.appendChild(li);
    }
  }
}

function showResult(jobId, filename) {
  progressFill.style.width = "100%";
  progressPercent.textContent = "100%";
  progressMessage.textContent = "Done.";
  resultBlock.hidden = false;
  resultFilename.textContent = filename;
  saveBtn.href = `/api/jobs/${jobId}/file`;
  downloadBtn.disabled = false;
  downloadBtn.querySelector(".btn-label").textContent = "Download";
}

function showError(message) {
  clearTimeout(pollTimer);
  progressBlock.hidden = true;
  errorBlock.hidden = false;
  errorMessage.textContent = message;
  downloadBtn.disabled = false;
  downloadBtn.querySelector(".btn-label").textContent = "Download";
}
