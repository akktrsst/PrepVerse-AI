// Browser voice layer: Web Speech API recognition (STT) + speechSynthesis (TTS).
// Free and client-side. Replies are spoken sentence by sentence while they stream in.
"use strict";

(() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  /** Make model text pleasant to hear: drop citations, markdown and URLs. */
  function speakable(text) {
    return text
      .replace(/\s*\[\d{1,2}\]/g, "")
      .replace(/```[\s\S]*?```/g, " (see the code on screen) ")
      .replace(/https?:\/\/\S+/g, "")
      .replace(/[*_#>`~|]/g, "")
      .replace(/^\s*[-•]\s+/gm, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  class VoiceController {
    /**
     * @param {{onState(s), onInterim(text), onFinal(text), onError(msg)}} handlers
     * States: idle | listening | thinking | speaking
     */
    constructor(handlers) {
      this.h = handlers;
      this.supported = { stt: !!Recognition, tts: "speechSynthesis" in window };
      this.state = "idle";
      this.lang = PV.store.get("pv.voice.lang", navigator.language?.startsWith("en-IN") ? "en-IN" : "en-US");
      this.rate = PV.store.get("pv.voice.rate", 1.05);
      this.voiceName = PV.store.get("pv.voice.name", null);
      this.handsFree = PV.store.get("pv.voice.handsFree", false);
      this.muted = false;
      this._buf = "";
      this._queue = 0;
      this._streamDone = true;
      this._rec = null;
      this._gotFinal = false;
    }

    setState(s) {
      this.state = s;
      this.h.onState?.(s);
    }

    voices() {
      if (!this.supported.tts) return [];
      const prefix = this.lang.split("-")[0];
      return speechSynthesis.getVoices().filter((v) => v.lang.replace("_", "-").startsWith(prefix));
    }

    // ---- Listening ----
    listen() {
      if (!this.supported.stt) { this.h.onError?.("Voice input isn't supported in this browser. Try Chrome or Edge."); return; }
      this.stopSpeaking(); // barge-in
      if (this._rec) { try { this._rec.abort(); } catch {} }
      const rec = new Recognition();
      rec.lang = this.lang;
      rec.interimResults = true;
      rec.continuous = false; // stops on a pause, then we send
      rec.maxAlternatives = 1;
      this._gotFinal = false;
      let finalText = "";

      rec.onresult = (e) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          if (r.isFinal) finalText += r[0].transcript;
          else interim += r[0].transcript;
        }
        this.h.onInterim?.((finalText + " " + interim).trim());
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          this.h.onError?.("Microphone access is blocked. Allow it in your browser's site settings.");
        } else if (e.error !== "no-speech" && e.error !== "aborted") {
          this.h.onError?.(`Voice input error: ${e.error}`);
        }
      };
      rec.onend = () => {
        this._rec = null;
        const text = finalText.trim();
        this.h.onInterim?.("");
        if (text) {
          this._gotFinal = true;
          this.setState("thinking");
          this.h.onFinal?.(text);
        } else if (this.state === "listening") {
          this.setState("idle");
        }
      };
      this._rec = rec;
      this.setState("listening");
      try { rec.start(); } catch { this.setState("idle"); }
    }

    stopListening() {
      if (this._rec) { try { this._rec.stop(); } catch {} }
    }

    // ---- Speaking (streamed) ----
    beginReply() {
      this._buf = "";
      this._streamDone = false;
      this._queue = 0;
    }

    /** Feed a streamed chunk; complete sentences are spoken immediately. */
    feed(chunk) {
      this._buf += chunk;
      // Everything up to the last sentence end that's followed by whitespace is complete.
      const m = this._buf.match(/^[\s\S]*[.!?\n](?=\s)/);
      if (m) {
        this._say(m[0]);
        this._buf = this._buf.slice(m[0].length);
      }
    }

    /** The reply finished streaming: speak whatever is left. */
    endReply() {
      this._streamDone = true;
      if (this._buf.trim()) this._say(this._buf);
      this._buf = "";
      if (this._queue === 0) this._finished();
    }

    _say(text) {
      const clean = speakable(text);
      if (!clean || this.muted || !this.supported.tts) return;
      const u = new SpeechSynthesisUtterance(clean);
      u.lang = this.lang;
      u.rate = this.rate;
      const voice = this.voices().find((v) => v.name === this.voiceName);
      if (voice) u.voice = voice;
      this._queue++;
      u.onend = u.onerror = () => {
        this._queue = Math.max(0, this._queue - 1);
        if (this._queue === 0 && this._streamDone) this._finished();
      };
      if (this.state !== "speaking") this.setState("speaking");
      speechSynthesis.speak(u);
    }

    _finished() {
      if (this.state === "listening") return;
      this.setState("idle");
      if (this.handsFree && this._gotFinal) setTimeout(() => { if (this.state === "idle") this.listen(); }, 350);
    }

    stopSpeaking() {
      if (!this.supported.tts) return;
      this._queue = 0;
      this._streamDone = true;
      this._buf = "";
      speechSynthesis.cancel();
      if (this.state === "speaking") this.setState("idle");
    }

    /** Stop everything (e.g. the user typed instead, or left the page). */
    reset() {
      this._gotFinal = false;
      if (this._rec) { try { this._rec.abort(); } catch {} }
      this.stopSpeaking();
      this.setState("idle");
    }
  }

  PV.VoiceController = VoiceController;
  PV.speakable = speakable;
})();
