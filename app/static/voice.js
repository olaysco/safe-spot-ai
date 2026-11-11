'use strict';
window.SafeSpotVoice = (() => {
  let active = null;
  function stop() {
    if (active) active.cancel();
  }
  function attach(textarea, button, status, onText) {
    if (!textarea || !button || !status) return;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition || !window.isSecureContext) {
      button.disabled = true;
      status.textContent = 'Voice input is unavailable in this browser. You can type your report.';
      return;
    }
    button.addEventListener('click', () => {
      if (active) { active.finish(); return; }
      const recognition = new Recognition();
      recognition.lang = 'en-GB';
      recognition.continuous = true;
      recognition.interimResults = true;
      let base = textarea.value.trimEnd(), accepted = '', ended = false, failed = false;
      const seen = new Set();
      function restore() {
        textarea.readOnly = false;
        button.disabled = false;
        button.textContent = 'Use voice input';
        button.setAttribute('aria-pressed', 'false');
        if (active === session) active = null;
      }
      const session = {
        cancel() { ended = true; restore(); recognition.abort(); },
        finish() { button.disabled = true; status.textContent = 'Finishing voice input…'; recognition.stop(); },
      };
      active = session;
      recognition.onstart = () => {
        if (!ended) status.textContent = 'Listening. Select Stop voice input when you finish.';
      };
      recognition.onresult = event => {
        if (ended) return;
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal && !seen.has(i)) {
            seen.add(i);
            accepted += (accepted ? ' ' : '') + result[0].transcript.trim();
          } else if (!result.isFinal) interim += result[0].transcript;
        }
        textarea.value = (base + (base && accepted ? ' ' : '') + accepted).slice(0, 8000);
        onText(textarea.value);
        status.textContent = interim ? 'Listening: ' + interim : 'Text added. Select Stop voice input to check it.';
      };
      recognition.onerror = event => {
        if (ended) return;
        failed = true;
        ended = true;
        const errors = {
          'not-allowed': 'Microphone access was not allowed. You can allow access in browser settings or type your report.',
          'audio-capture': 'No microphone is available. Connect a microphone or type your report.',
          'no-speech': 'No speech was detected. Try again or type your report.',
          'network': 'The speech service is unavailable. Try again or type your report.',
        };
        status.textContent = errors[event.error] || 'Voice input stopped. You can try again or type your report.';
        button.disabled = false;
        restore();
        recognition.abort();
      };
      recognition.onend = () => {
        if (ended) return;
        ended = true;
        button.disabled = false;
        restore();
        if (!failed) status.textContent = accepted ? 'Check and edit the text before you continue.' : 'No text was added. Try again or type your report.';
      };
      textarea.readOnly = true;
      button.textContent = 'Stop voice input';
      button.setAttribute('aria-pressed', 'true');
      status.textContent = 'Starting voice input…';
      try { recognition.start(); }
      catch { ended = true; restore(); status.textContent = 'Voice input could not start. You can type your report.'; }
    });
  }
  window.addEventListener('pagehide', stop);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  return { attach, stop };
})();
