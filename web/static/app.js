/* ===================================================
   Musicalopment – Frontend (NO axios, pure fetch)
   =================================================== */

(function () {
  "use strict";

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
  const $statDur     = document.getElementById("stat-dur");

  const $video       = document.getElementById("video-player");
  const $btnTap      = document.getElementById("btn-tap");
  const $tapSub      = document.getElementById("tap-sub");
  const $renderProg     = document.getElementById("render-progress");
  const $renderProgFill = document.getElementById("render-progress-fill");
  const $renderProgText = document.getElementById("render-progress-text");
  const $toggleBars  = document.getElementById("toggle-bars");

  const $resMeter    = document.getElementById("res-meter");
  const $resBars     = document.getElementById("res-bars");
  const $resultVideo = document.getElementById("result-player");
  const $downloadLink = document.getElementById("download-link");
  const $btnRestart  = document.getElementById("btn-restart");

  let jobId = null;
  let beatTimes = [];
  let selectedMeter = 4;

  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function showSection(section) {
    [$upload, $tap, $result].forEach(s => s.classList.add("hidden"));
    section.classList.remove("hidden");
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // --- Meter button selection ---
  document.querySelectorAll(".meter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".meter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedMeter = parseInt(btn.dataset.meter, 10);
    });
  });

  // =========================================================
  //  STEP 1 – Upload
  // =========================================================

  $uploadArea.addEventListener("click", () => $fileInput.click());

  $fileInput.addEventListener("change", () => {
    const file = $fileInput.files[0];
    if (!file) return;
    uploadVideo(file);
  });

  function uploadVideo(file) {
    show($progress);
    hide($processingMsg);
    $progressFill.style.width = "0%";
    $progressText.textContent = "Uploading…";

    const formData = new FormData();
    formData.append("video", file);

    const xhr = new XMLHttpRequest();
    let serverResponded = false;

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        $progressFill.style.width = pct + "%";
        $progressText.textContent = "Uploading… " + pct + "%";
      }
    });

    xhr.addEventListener("load", () => {
      serverResponded = true;
      hide($progress);
      hide($processingMsg);

      if (xhr.status >= 200 && xhr.status < 300) {
        handleStep1Result(JSON.parse(xhr.responseText));
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

    xhr.timeout = 300000; // 5 min max
    xhr.addEventListener("timeout", () => {
      serverResponded = true;
      hide($progress);
      hide($processingMsg);
      alert("Processing took too long. Try a shorter video (under 1 minute).");
    });

    xhr.open("POST", "/api/upload");
    xhr.send(formData);
  }

  function handleStep1Result(data) {
    jobId = data.job_id;
    beatTimes = data.beat_times || [];

    $statBpm.textContent = data.bpm;
    $statBeats.textContent = data.total_beats;
    $statDur.textContent = data.duration + "s";

    $video.src = data.original_video;
    $video.load();

    showSection($tap);

    $btnTap.disabled = true;
    $tapSub.textContent = "play video first";

    $video.addEventListener("play", function onPlay() {
      $btnTap.disabled = false;
      $tapSub.textContent = "tap when you hear the ONE";
      $video.removeEventListener("play", onPlay);
    });
  }

  // =========================================================
  //  STEP 2 – Tap the ONE → rerender (pure math + overlay)
  // =========================================================

  $btnTap.addEventListener("click", () => {
    if ($video.paused || !jobId) return;

    const tapTime = $video.currentTime;
    const nearest = findNearestBeat(tapTime);
    $tapSub.textContent = "Tapped at " + tapTime.toFixed(2) + "s → beat at " + nearest.toFixed(2) + "s";
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
    show($renderProg);
    $renderProgFill.style.width = "0%";
    $renderProgText.textContent = "Rendering " + selectedMeter + "/4 counting… 0%";

    try {
      const resp = await fetch("/api/rerender", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          tap_time: tapTime,
          meter: selectedMeter,
          show_bars: $toggleBars.checked,
        }),
      });

      if (!resp.ok) {
        let msg = "Render failed (status " + resp.status + ")";
        try { msg = (await resp.json()).error || msg; } catch (_) {}
        throw new Error(msg);
      }

      pollProgress(jobId);

    } catch (e) {
      hide($renderProg);
      alert(e.message);
      $btnTap.disabled = false;
    }
  }

  function pollProgress(id) {
    const iv = setInterval(async () => {
      try {
        const r = await fetch("/api/progress/" + id);
        const d = await r.json();
        const pct = d.pct || 0;

        $renderProgFill.style.width = pct + "%";
        $renderProgText.textContent = "Rendering… " + pct + "%";

        if (d.status === "done") {
          clearInterval(iv);
          hide($renderProg);
          handleStep2Result(d.result);
        } else if (d.status === "error") {
          clearInterval(iv);
          hide($renderProg);
          alert("Render error: " + (d.error || "unknown"));
          $btnTap.disabled = false;
        }
      } catch (_) {
        // network hiccup — keep polling
      }
    }, 1500);
  }

  function handleStep2Result(data) {
    $resMeter.textContent = data.meter + "/4";
    $resBars.textContent = data.total_bars;

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
    hide($renderProg);
    showSection($upload);
  });

})();
