/* Local Transcribe — frontend (v3, WebSocket live-streaming)
 *
 * Flow:
 *   - MediaRecorder collects audio chunks in `recordedChunks`
 *   - Every LIVE_INTERVAL_MS (~1200 ms), all collected chunks are concatenated
 *     into ONE complete WebM blob and pushed down the WebSocket
 *   - Server transcribes and returns {"type":"partial","text":..}
 *   - Live text is shown in the status bar ONLY (textarea stays clean until stop)
 *   - On "." (stop), we send "stop" over the WS → server replies with final →
 *     final text is appended into the textarea (caret-aware, user-edits safe)
 *
 * Why WebSocket (vs POST polling)?
 *   ~1.2s update cadence with <100ms server RTT → feels instant.
 *   No request overhead, no upload-spike every few seconds.
 *
 * Why complete blobs (not raw chunks)?
 *   Chrome's MediaRecorder.timeslice produces non-self-contained WebM chunks.
 *   Sending the full so-far blob gives the decoder a valid container.
 */

(() => {
  'use strict';

  // ---------- DOM ----------
  const $transcript = document.getElementById('transcript');
  const $hintOverlay = document.getElementById('hintOverlay');
  const $watermark = document.querySelector('.watermark');
  const $btnRecord  = document.getElementById('btnRecord');
  const $btnPause   = document.getElementById('btnPause');
  const $btnStop    = document.getElementById('btnStop');
  const $btnCopy    = document.getElementById('btnCopy');
  const $btnClear   = document.getElementById('btnClear');
  const $statusDot  = document.getElementById('statusDot');
  const $statusText = document.getElementById('statusText');
  const $statusMeta = document.getElementById('statusMeta');
  const $detectedLang = document.getElementById('detectedLang');

  const LIVE_INTERVAL_MS = 1500;

  // ---------- State ----------
  const state = {
    phase: 'idle',                  // idle | recording | paused | processing
    mediaRecorder: null,
    mediaStream: null,
    recordedChunks: [],
    ws: null,
    // Caret-aware append state
    appendStart: 0,
    userEditedSinceUpdate: false,
    // Timing
    startedAt: 0,
    pausedTotalMs: 0,
    pausedAt: 0,
    timerInterval: null,
    liveTimer: null,
    inFlight: false,
  };

  // ---------- Status helpers ----------
  function setPhase(phase, meta = '') {
    state.phase = phase;
    $statusDot.className = 'status-dot ' + phase;
    $statusText.textContent =
      phase === 'idle'       ? 'idle' :
      phase === 'recording'  ? 'recording' :
      phase === 'paused'     ? 'paused' :
      phase === 'processing' ? 'processing' : phase;
    $statusMeta.textContent = meta;
    $btnRecord.classList.toggle('is-recording', phase === 'recording');
    $btnPause.classList.toggle('is-paused',     phase === 'paused');
    $btnRecord.disabled = phase === 'processing';
    $btnPause.disabled  = phase !== 'recording';
    $btnStop.disabled   = !(phase === 'recording' || phase === 'paused');
    updateHintVisibility();
  }

  // Hint overlay: shown only when the textarea is empty AND we're not
  // actively recording. As soon as there's text (typed or transcribed) or
  // the user is mid-recording, hide it so it doesn't overlap the live
  // transcript.
  // The watermark logo (.watermark) in the bottom-right follows the same
  // rule — it disappears together with the hint overlay so it never
  // collides with real text in the textarea.
  function updateHintVisibility() {
    const hasText = $transcript.value.trim().length > 0;
    const recording = state.phase === 'recording' || state.phase === 'paused' || state.phase === 'processing';
    const shouldHide = hasText || recording;
    $hintOverlay.classList.toggle('hidden', shouldHide);
    $hintOverlay.setAttribute('aria-hidden', String(shouldHide));
    if ($watermark) $watermark.classList.toggle('hidden', shouldHide);
  }

  function showToast(msg) {
    let t = document.querySelector('.toast');
    if (!t) {
      t = document.createElement('div');
      t.className = 'toast';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => t.classList.remove('show'), 1800);
  }

  function fmtDuration(ms) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }

  function elapsedMs() {
    if (!state.startedAt) return 0;
    return Date.now() - state.startedAt - state.pausedTotalMs;
  }

  // ---------- Timer ----------
  function startTimer() {
    state.startedAt = Date.now();
    state.pausedTotalMs = 0;
    state.pausedAt = 0;
    if (state.timerInterval) clearInterval(state.timerInterval);
    state.timerInterval = setInterval(() => {
      // Status bar: just the duration. No preview text here — that would
      // overlap with the live textarea stream and cause flicker.
      $statusMeta.textContent = fmtDuration(elapsedMs());
    }, 250);
  }

  function stopTimer() {
    if (state.timerInterval) clearInterval(state.timerInterval);
    state.timerInterval = null;
  }

  // ---------- WebSocket ----------
  function openWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/transcribe`;
    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    ws.onmessage = onWSMessage;
    ws.onerror = (e) => { console.warn('WS error', e); showToast('WS error'); };
    ws.onclose = () => { if (state.ws === ws) state.ws = null; };
    state.ws = ws;
  }

  function onWSMessage(ev) {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'partial') {
      state.inFlight = false;
      // The live text already streams into the textarea below — no need to
      // repeat it in the status bar (was causing distracting flicker).
      // Status bar just shows the phase + duration; nothing more.
      if (msg.language) {
        $detectedLang.textContent = msg.language;
      }
      const t = (msg.text || '').trim();
      if (t && !state.userEditedSinceUpdate) {
        appendAutoText(t, /*replace=*/true);
      }
    } else if (msg.type === 'stopped') {
      // Server confirmed end of stream — final transcript is in msg.text
      state.inFlight = false;
      const finalText = (msg.text || '').trim();
      if (finalText) appendAutoText(finalText, /*replace=*/true);
      showToast('Transcription complete');
      closeWS();
    } else if (msg.type === 'error') {
      state.inFlight = false;
      showToast('Server error: ' + msg.message);
    }
  }

  function closeWS() {
    if (state.ws) {
      try { state.ws.close(); } catch {}
      state.ws = null;
    }
  }

  // ---------- Recording ----------
  async function startRecording() {
    if (state.phase !== 'idle') return;

    try {
      state.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (e) {
      showToast('Mic permission denied: ' + e.message);
      console.error(e);
      return;
    }

    const mimeCandidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/mp4',
    ];
    const mimeType = mimeCandidates.find(m => MediaRecorder.isTypeSupported(m)) || '';
    state.mediaRecorder = new MediaRecorder(
      state.mediaStream,
      mimeType ? { mimeType } : {},
    );
    state.recordedChunks = [];
    state.appendStart = $transcript.value.length;
    state.userEditedSinceUpdate = false;

    state.mediaRecorder.ondataavailable = (ev) => {
      if (!ev.data || ev.data.size === 0) return;
      state.recordedChunks.push(ev.data);
    };
    state.mediaRecorder.onerror = (ev) => {
      console.error('MediaRecorder error:', ev.error || ev);
      showToast('Recorder error: ' + (ev.error?.message || 'unknown'));
    };

    state.mediaRecorder.start(750);   // collect chunks every ~750 ms
    openWS();
    setPhase('recording');
    startTimer();

    // Send the COMPLETE-so-far audio blob every LIVE_INTERVAL_MS
    state.liveTimer = setInterval(sendLiveChunk, LIVE_INTERVAL_MS);
  }

  async function sendLiveChunk() {
    if (state.inFlight) return;
    if (state.recordedChunks.length === 0) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    if (state.phase !== 'recording' && state.phase !== 'paused') return;

    state.inFlight = true;
    try {
      // Concatenate all collected chunks into one complete WebM blob.
      // This is a valid container that faster-whisper / mlx-whisper can decode.
      const blob = new Blob(
        state.recordedChunks.slice(),
        { type: state.mediaRecorder.mimeType || 'audio/webm' },
      );
      const buf = await blob.arrayBuffer();
      state.ws.send(buf);
    } catch (e) {
      console.warn('sendLiveChunk failed:', e);
      state.inFlight = false;
    }
  }

  function pauseRecording() {
    if (state.phase !== 'recording' || !state.mediaRecorder) return;
    state.mediaRecorder.pause();
    state.pausedAt = Date.now();
    setPhase('paused');
  }

  function resumeRecording() {
    if (state.phase !== 'paused' || !state.mediaRecorder) return;
    state.mediaRecorder.resume();
    state.pausedTotalMs += Date.now() - state.pausedAt;
    setPhase('recording');
  }

  async function stopRecording() {
    if (state.phase !== 'recording' && state.phase !== 'paused') return;
    setPhase('processing', 'finalizing…');

    // Stop live-streaming
    if (state.liveTimer) clearInterval(state.liveTimer);
    state.liveTimer = null;

    // Wait for recorder.onstop BEFORE touching tracks (fixes Chromium's
    // "Unhandled stop reason: error" when the stream ends mid-finalize)
    await new Promise((resolve) => {
      state.mediaRecorder.onstop = resolve;
      try { state.mediaRecorder.stop(); } catch { resolve(); }
    });
    state.mediaStream.getTracks().forEach(t => { try { t.stop(); } catch {} });

    // Tell server to flush its last partial → server replies with "stopped"
    // containing the final text (last partial already includes everything).
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      try { state.ws.send('stop'); } catch {}
      // Give server ~500 ms to reply
      await new Promise(r => setTimeout(r, 500));
    }
    closeWS();

    stopTimer();
    setPhase('idle');
  }

  // ---------- Caret-aware text insertion ----------
  $transcript.addEventListener('input', () => {
    if ($transcript.selectionStart < state.appendStart) {
      state.userEditedSinceUpdate = true;
    }
    updateHintVisibility();
  });

  function appendAutoText(newText, replace = false) {
    if (!newText) return;
    const cur = $transcript.value;
    let next, newAppendStart;

    if (replace && !state.userEditedSinceUpdate) {
      // REPLACE the pending region. `appendStart` = the BEGINNING of the
      // pending region (where the next auto-insert should start). We keep
      // that position; the rest of the textarea is discarded and replaced
      // with newText. The new pending region still starts at appendStart.
      const before = cur.slice(0, state.appendStart).replace(/\s+$/, '');
      const sep = before.length ? ' ' : '';
      newAppendStart = before.length + sep.length;   // unchanged position
      next = before + sep + newText;
    } else {
      // APPEND at the end (user has edited, so we don't clobber anything).
      // New pending region starts where the appended text begins.
      const before = cur.replace(/\s+$/, '');
      const sep = before.length ? ' ' : '';
      newAppendStart = (before + sep).length;
      next = before + sep + newText;
    }

    $transcript.value = next;
    state.appendStart = newAppendStart;   // BEGINNING of pending, not end!
    state.userEditedSinceUpdate = false;
    updateHintVisibility();
    // Don't move caret — user might be editing elsewhere.
  }

  // ---------- Buttons ----------
  function toggleRecord() {
    if (state.phase === 'idle') startRecording();
    else if (state.phase === 'recording') pauseRecording();
    else if (state.phase === 'paused') resumeRecording();
  }
  $btnRecord.addEventListener('click', toggleRecord);
  $btnPause.addEventListener('click', () => {
    if (state.phase === 'recording') pauseRecording();
    else if (state.phase === 'paused') resumeRecording();
  });
  $btnStop.addEventListener('click', stopRecording);
  $btnCopy.addEventListener('click', copyTranscript);
  $btnClear.addEventListener('click', () => {
    if (state.phase !== 'idle') { showToast('Stop recording first'); return; }
    $transcript.value = '';
    state.appendStart = 0;
    state.userEditedSinceUpdate = false;
    updateHintVisibility();
    $transcript.focus();
  });

  async function copyTranscript() {
    const text = $transcript.value;
    if (!text) { showToast('Nothing to copy'); return; }
    try {
      await navigator.clipboard.writeText(text);
      showToast('Copied to clipboard');
    } catch {
      $transcript.select();
      try { document.execCommand('copy'); showToast('Copied'); }
      catch { showToast('Copy failed'); }
    }
  }

  // ---------- Hotkeys ----------
  document.addEventListener('keydown', (ev) => {
    const isTypingInTextarea = ev.target === $transcript;
    const isTypingAnywhere = ['INPUT', 'TEXTAREA'].includes(ev.target.tagName);

    if (ev.code === 'Space') {
      if (isTypingInTextarea) return;
      ev.preventDefault();
      toggleRecord();
    } else if (ev.key === '.' && !isTypingAnywhere) {
      ev.preventDefault();
      if (state.phase === 'recording' || state.phase === 'paused') stopRecording();
    }
  });

  // ---------- Init ----------
  setPhase('idle');
  $transcript.focus();

  fetch('/api/health')
    .then(r => r.json())
    .then(h => {
      console.info(`Local Transcribe ready (backend=${h.backend}, model=${h.model}, device=${h.device})`);
    })
    .catch(e => console.warn('Backend not reachable:', e));
})();