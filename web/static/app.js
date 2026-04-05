/* ===================================================
   Musicalopment – Frontend Logic
   NO axios. Pure native fetch().
   =================================================== */

(function () {
  "use strict";

  // --- DOM refs ---
  const $upload      = document.getElementById("section-upload");
  const $tap         = document.getElementById("section-tap");
  const $result      = document.getElementById("section-result");

  const $fileInput   = document.getElementById("file-input");
  const $uploadArea  = document.getElementById("upload-area");
  const $progress    = document.getElementById("upload-progress");
  const $progressFill = document.getElementById("progress-fill");
  const $progressText = document.getElementById("progress-text");
  const $processingMsg = document.getElementById("processing-msg");

  const $statBpm     = document.getElementById("stat-bpm");
  const $statBeats   = document.getElementById("stat-beats");
  const $statMeter   = document.getElementById("stat-meter");

  const $video       = document.getElementById("video-player");
  const $btnTap      = document.getElementById("btn-tap");
  const $tapSub      = document.getElementById("tap-sub");
  const $analysisWin = document.getElementById("analysis-window");
  const $tapStatus   = document.getElementById("tap-status");
  const $tapStatusTxt = document.getElementById("tap-status-text");

  const $resMeter    = document.getElementById("res-meter");
  const $resMeasures = document.getElementById("res-measures");
  const $resConf     = document.getElementById("res-conf");
  const $resultVideo = document.getElementById("result-player");
  const $downloadLink = document.getElementById("download-link");
  const $btnRestart  = document.getElementById("btn-restart");

  // --- State ---
  let jobId = null;
  let beatTimes = [];

  // --- Helpers ---
  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function showSection(section) {
    [$upload, $tap, $result].forEach(s => s.classList.add("hidden"));
    section.classList.remove("hidden");
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // =========================================================
  //  STEP 1 – Upload & Process
  // =========================================================

  $uploadArea.addEventListener("click", () => $fileInput.click());

  $fileInput.addEventListener("change", () => {
    const file = $fileInput.files[0];
    if (!file) return;
    uploadVideo(file);
  });

  async function uploadVideo(file) {
    // Show progress
    show($progress);
    hide($processingMsg);
    $progressFill.style.width = "0%";
    $progressText.textContent = "Uploading…";

    const formData = new FormData();
    formData.append("video", file);

    // Use XMLHttpRequest for upload progress (fetch doesn't support it)
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        $progressFill.style.width = pct + "%";
        $progressText.textContent = `Uploading… ${pct}%`;
      }
    });

    let serverResponded = false;

    xhr.addEventListener("load", () => {
      serverResponded = true;
      hide($progress);
      hide($processingMsg);

      if (xhr.status >= 200 && xhr.status < 300) {
        const data = JSON.parse(xhr.responseText);
        handleStep1Result(data);
      } else {
        let msg = "Upload failed";
        try { msg = JSON.parse(xhr.responseText).error || msg; } catch (_) {}
        alert(msg);
      }
    });

    xhr.addEventListener("error", () => {
      serverResponded = true;
      hide($progress);
      hide($processingMsg);
      alert("Network error — check your connection.");
    });

    xhr.upload.addEventListener("load", () => {
      if (serverResponded) return;
      $progressFill.style.width = "100%";
      $progressText.textContent = "Processing…";
      setTimeout(() => {
        if (serverResponded) return;
        hide($progress);
        show($processingMsg);
      }, 400);
    });

    xhr.open("POST", "/api/upload");
    xhr.send(formData);
  }

  function handleStep1Result(data) {
    hide($processingMsg);

    jobId = data.job_id;
    beatTimes = data.beat_times || [];

    // Fill stats
    $statBpm.textContent = data.bpm;
    $statBeats.textContent = data.total_beats;
    $statMeter.textContent = data.auto_meter + "/4";

    // Load step-1 video
    $video.src = data.step1_video;
    $video.load();

    showSection($tap);

    // Enable tap button once video starts playing
    $btnTap.disabled = true;
    $tapSub.textContent = "play video first";

    $video.addEventListener("play", function onPlay() {
      $btnTap.disabled = false;
      $tapSub.textContent = "tap when you hear the ONE";
      $video.removeEventListener("play", onPlay);
    });
  }

  // =========================================================
  //  STEP 2 – Tap the ONE & Re-render
  // =========================================================

  $btnTap.addEventListener("click", () => {
    if ($video.paused || !jobId) return;

    const tapTime = $video.currentTime;
    const nearestBeat = findNearestBeat(tapTime);
    $tapSub.textContent = `Tapped at ${tapTime.toFixed(2)}s → beat at ${nearestBeat.toFixed(2)}s`;
    $btnTap.disabled = true;

    rerender(tapTime);
  });

  function findNearestBeat(t) {
    let best = beatTimes[0] || 0;
    let bestDist = Math.abs(t - best);
    for (const bt of beatTimes) {
      const d = Math.abs(t - bt);
      if (d < bestDist) { bestDist = d; best = bt; }
    }
    return best;
  }

  async function rerender(tapTime) {
    show($tapStatus);
    $tapStatusTxt.textContent = "Detecting meter & re-rendering…";

    const analysisWindow = parseFloat($analysisWin.value) || 10;

    try {
      const resp = await fetch("/api/tap-rerender", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          tap_time: tapTime,
          analysis_window: analysisWindow,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.error || "Re-render failed");
      }

      const data = await resp.json();
      handleStep2Result(data);

    } catch (e) {
      alert(e.message);
      $btnTap.disabled = false;
    } finally {
      hide($tapStatus);
    }
  }

  function handleStep2Result(data) {
    $resMeter.textContent = data.detected_meter + "/4";
    $resMeasures.textContent = data.total_measures;
    $resConf.textContent = data.confidence.toFixed(2);

    $resultVideo.src = data.final_video;
    $resultVideo.load();

    $downloadLink.href = data.final_video;
    $downloadLink.download = "beat_counted_video.mp4";

    showSection($result);
  }

  // =========================================================
  //  Restart
  // =========================================================

  $btnRestart.addEventListener("click", () => {
    jobId = null;
    beatTimes = [];
    $fileInput.value = "";
    $video.src = "";
    $resultVideo.src = "";
    $btnTap.disabled = true;
    $tapSub.textContent = "play video first";
    hide($progress);
    hide($processingMsg);
    hide($tapStatus);
    showSection($upload);
  });

})();
