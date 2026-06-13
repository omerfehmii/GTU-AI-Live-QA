"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Brain, Radio, Zap, PlaySquare } from "lucide-react";

import { getJson, resolveBackendAssetUrl } from "@/lib/api";
import type { AvatarState, LiveState, PlaybackItem, Question } from "@/lib/types";
import { TypewriterText } from "@/components/typewriter-text";

const AvatarStage = dynamic(
  () => import("@/components/avatar-stage").then((module) => module.AvatarStage),
  {
    ssr: false,
    loading: () => (
      <div className="avatar-stage-loading w-full h-full flex items-center justify-center text-[#A1A1AA]">
        <span>Yükleniyor...</span>
      </div>
    ),
  },
);

const EMPTY_LIVE_STATE: LiveState = {
  avatar_state: "idle",
  current_phase: "idle",
  playback_item: null,
  current_question: null,
  latest_answered: null,
  queue: [],
  queue_size: 0,
  answer_ready_count: 0,
  speech_queue_size: 0,
  active_streams: 0,
  generated_at: new Date(0).toISOString(),
};

function formatTime(value?: string | null) {
  if (!value) {
    return "";
  }

  return new Date(value).toLocaleTimeString("tr-TR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function BroadcastStage() {
  const [liveState, setLiveState] = useState<LiveState>(EMPTY_LIVE_STATE);
  const [isAudioPlaying, setIsAudioPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState("");
  
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioLevelRef = useRef(0);
  const hueRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let rafId: number;
    const update = () => {
      if (hueRef.current) {
        const level = audioLevelRef.current || 0;
        const scale = 1 + Math.min(1, Math.max(0, level * 2)) * 0.4;
        hueRef.current.style.setProperty('--vol-scale', scale.toString());
      }
      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const audioPlaybackRef = useRef({
    currentTime: 0,
    duration: 0,
    isPlaying: false,
  });
  const lastPlayedSpeechKeyRef = useRef<string | null>(null);
  const pendingAudioKeyRef = useRef<string | null>(null);

  // Time updating
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(now.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  async function refresh() {
    try {
      const state = await getJson<LiveState>("/live/state");
      setLiveState(state);
    } catch {
      return;
    }
  }

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => {
      void refresh();
    }, 1600);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const retryAudio = () => {
      if (!pendingAudioKeyRef.current || !audioRef.current) {
        return;
      }

      audioRef.current.play().then(() => {
        pendingAudioKeyRef.current = null;
      }).catch(() => undefined);
    };

    window.addEventListener("pointerdown", retryAudio);
    window.addEventListener("keydown", retryAudio);
    return () => {
      window.removeEventListener("pointerdown", retryAudio);
      window.removeEventListener("keydown", retryAudio);
    };
  }, []);

  useEffect(() => {
    const audio = new Audio();
    audio.crossOrigin = "anonymous";
    audioRef.current = audio;
    const meterRef: {
      analyser: AnalyserNode;
      context: AudioContext;
      data: Uint8Array<ArrayBuffer>;
      playbackRafId: number | null;
      rafId: number | null;
      source: MediaElementAudioSourceNode;
    } = {
      analyser: null as unknown as AnalyserNode,
      context: null as unknown as AudioContext,
      data: new Uint8Array(new ArrayBuffer(0)),
      playbackRafId: null,
      rafId: null,
      source: null as unknown as MediaElementAudioSourceNode,
    };

    const syncPlayback = () => {
      audioPlaybackRef.current = {
        currentTime: audio.currentTime,
        duration: Number.isFinite(audio.duration) ? audio.duration : 0,
        isPlaying: !audio.paused && !audio.ended,
      };

      if (!audio.paused && !audio.ended) {
        meterRef.playbackRafId = window.requestAnimationFrame(syncPlayback);
      } else {
        meterRef.playbackRafId = null;
      }
    };

    const startPlaybackSync = () => {
      if (meterRef.playbackRafId === null) {
        meterRef.playbackRafId = window.requestAnimationFrame(syncPlayback);
      }
    };

    const stopPlaybackSync = () => {
      if (meterRef.playbackRafId !== null) {
        window.cancelAnimationFrame(meterRef.playbackRafId);
        meterRef.playbackRafId = null;
      }

      audioPlaybackRef.current = {
        currentTime: audio.currentTime,
        duration: Number.isFinite(audio.duration) ? audio.duration : 0,
        isPlaying: false,
      };
    };

    const stopMeter = () => {
      if (meterRef.rafId !== null) {
        window.cancelAnimationFrame(meterRef.rafId);
        meterRef.rafId = null;
      }
      audioLevelRef.current = 0;
    };

    const readMeter = () => {
      if (!meterRef.analyser || audio.paused || audio.ended) {
        stopMeter();
        return;
      }

      meterRef.analyser.getByteTimeDomainData(meterRef.data);
      let sum = 0;
      for (const value of meterRef.data) {
        const centered = (value - 128) / 128;
        sum += centered * centered;
      }
      const rms = Math.sqrt(sum / meterRef.data.length);
      const level = Math.min(1, Math.max(0, (rms - 0.015) * 8));
      audioLevelRef.current = audioLevelRef.current * 0.62 + level * 0.38;
      meterRef.rafId = window.requestAnimationFrame(readMeter);
    };

    const startMeter = () => {
      try {
        if (!meterRef.context) {
          const AudioContextConstructor =
            window.AudioContext ??
            (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
          if (!AudioContextConstructor) {
            return;
          }

          meterRef.context = new AudioContextConstructor();
          meterRef.analyser = meterRef.context.createAnalyser();
          meterRef.analyser.fftSize = 512;
          meterRef.analyser.smoothingTimeConstant = 0.54;
          meterRef.data = new Uint8Array(new ArrayBuffer(meterRef.analyser.fftSize));
          meterRef.source = meterRef.context.createMediaElementSource(audio);
          meterRef.source.connect(meterRef.analyser);
          meterRef.analyser.connect(meterRef.context.destination);
        }

        void meterRef.context.resume();
        if (meterRef.rafId === null) {
          meterRef.rafId = window.requestAnimationFrame(readMeter);
        }
      } catch {
        audioLevelRef.current = 0;
      }
    };

    const markPlaying = () => {
      setIsAudioPlaying(true);
      startPlaybackSync();
      startMeter();
    };
    const markStopped = () => {
      setIsAudioPlaying(false);
      stopPlaybackSync();
      stopMeter();
    };

    audio.addEventListener("playing", markPlaying);
    audio.addEventListener("play", markPlaying);
    audio.addEventListener("pause", markStopped);
    audio.addEventListener("ended", markStopped);
    audio.addEventListener("error", markStopped);

    return () => {
      audio.pause();
      stopPlaybackSync();
      stopMeter();
      meterRef.source?.disconnect();
      meterRef.analyser?.disconnect();
      void meterRef.context?.close();
      audio.removeEventListener("playing", markPlaying);
      audio.removeEventListener("play", markPlaying);
      audio.removeEventListener("pause", markStopped);
      audio.removeEventListener("ended", markStopped);
      audio.removeEventListener("error", markStopped);
      audioRef.current = null;
    };
  }, []);

  const playbackItem = liveState.playback_item;
  const isAnswerPlayback = playbackItem?.kind === "answer";
  const speechKey = playbackItem?.speech_key ?? null;
  const speechAudioUrl = resolveBackendAssetUrl(playbackItem?.audio_url);
  const displayQuestion = isAnswerPlayback
    ? liveState.current_question ?? liveState.latest_answered
    : liveState.current_question;
  const visibleSpeechText = playbackItem?.text ?? "";
  const visibleAnswerText = isAnswerPlayback
    ? displayQuestion?.answer?.content ?? playbackItem?.text ?? ""
    : "";
  const backendWantsSpeech = Boolean(playbackItem) && liveState.avatar_state === "speaking";
  const effectiveAvatarState: AvatarState = isAudioPlaying || backendWantsSpeech ? "speaking" : liveState.avatar_state;

  useEffect(() => {
    const audio = audioRef.current;
    pendingAudioKeyRef.current = null;
    audioLevelRef.current = 0;
    audioPlaybackRef.current = {
      currentTime: 0,
      duration: 0,
      isPlaying: false,
    };

    if (audio && !audio.paused) {
      audio.pause();
      audio.currentTime = 0;
    }

    setIsAudioPlaying(false);
  }, [speechKey]);

  useEffect(() => {
    if (
      !backendWantsSpeech ||
      !speechKey ||
      !speechAudioUrl ||
      lastPlayedSpeechKeyRef.current === speechKey
    ) {
      return;
    }

    lastPlayedSpeechKeyRef.current = speechKey;
    const audio = audioRef.current;
    if (!audio) {
      return;
    }

    audioPlaybackRef.current = {
      currentTime: 0,
      duration: (playbackItem?.audio_duration_ms ?? 0) / 1000,
      isPlaying: false,
    };
    audio.src = speechAudioUrl;
    audio.currentTime = 0;
    audio.play().then(() => {
      pendingAudioKeyRef.current = null;
    }).catch(() => {
      pendingAudioKeyRef.current = speechKey;
    });
  }, [backendWantsSpeech, playbackItem?.audio_duration_ms, speechAudioUrl, speechKey]);


  return (
    <main className="obs-canvas">
      {/* Dynamic Mesh Background */}
      <div className={`obs-ambient-glow ${effectiveAvatarState}`} />

      <div className="obs-screen">
        <div className="obs-logo-container">
          <div className="obs-logo">GTÜ AI</div>
          <div className="obs-logo-badge">STUDIO</div>
        </div>
      </div>

      <div className="obs-content-layout">
        <motion.div 
          initial={{ opacity: 0, y: -20, scale: 0.95, filter: "blur(10px)" }}
          animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
          className="obs-media-card"
        >
          <div className="obs-media-placeholder">
            <PlaySquare className="w-12 h-12 text-[#A1A1AA] mb-4 opacity-50" />
            <span className="text-[#A1A1AA] text-sm tracking-widest uppercase font-medium">Video Oynatıcı</span>
          </div>
        </motion.div>

        <AnimatePresence mode="popLayout">
          {displayQuestion && (
            <motion.div 
              key={displayQuestion.id || "q"}
              initial={{ opacity: 0, y: 30, scale: 0.98, filter: "blur(10px)" }}
              animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: 20, scale: 0.98, filter: "blur(10px)" }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="obs-qa-card"
            >
              <h2 className="obs-q">{displayQuestion.content}</h2>
              {visibleAnswerText && (
                <motion.p 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.3 }}
                  className="obs-a"
                >
                  <TypewriterText text={visibleAnswerText} speed={35} />
                </motion.p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="obs-streamer">
        <div ref={hueRef} className={`obs-streamer-hue ${effectiveAvatarState}`} />
        
        <div className="obs-avatar-canvas">
          <AvatarStage
            audioDurationMs={playbackItem?.audio_duration_ms ?? null}
            audioLevelRef={audioLevelRef}
            audioPlaybackRef={audioPlaybackRef}
            speechKey={speechKey}
            speechText={visibleSpeechText}
            state={effectiveAvatarState}
            theme="studio"
          />
        </div>
        
        <div className="obs-streamer-badges">
          <motion.div 
            layout
            className={`obs-badge obs-badge-${effectiveAvatarState}`}
          >
             {effectiveAvatarState === "speaking" ? (
                <><Mic className="obs-badge-icon" /> CANLI SES</>
             ) : effectiveAvatarState === "thinking" ? (
                <><Brain className="obs-badge-icon" /> SENTEZLENİYOR</>
             ) : (
                <><Radio className="obs-badge-icon" /> BEKLENİYOR</>
             )}
          </motion.div>

          <AnimatePresence mode="popLayout">
            {effectiveAvatarState === "speaking" && (
              <motion.div 
                initial={{ opacity: 0, width: 0, x: -10 }}
                animate={{ opacity: 1, width: "auto", x: 0 }}
                exit={{ opacity: 0, width: 0, x: -10 }}
                className="overflow-hidden"
              >
                <AudioVisualizer audioLevelRef={audioLevelRef} isSpeaking={true} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

      </div>
    </main>
  );
}

function AudioVisualizer({ audioLevelRef, isSpeaking }: { audioLevelRef: React.MutableRefObject<number>, isSpeaking: boolean }) {
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    let rafId: number;
    const update = () => {
      const baseLevel = audioLevelRef.current || 0;
      barsRef.current.forEach((bar, i) => {
        if (!bar) return;
        if (!isSpeaking) {
          bar.style.transform = `scaleY(0.1)`;
          return;
        }
        const multiplier = 0.6 + Math.sin(Date.now() / 150 + i * 0.5) * 0.4;
        const level = Math.max(0.1, Math.min(1, baseLevel * multiplier * 2));
        bar.style.transform = `scaleY(${level})`;
      });
      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, [audioLevelRef, isSpeaking]);

  return (
    <div className={`obs-visualizer ${isSpeaking ? "active" : ""}`}>
      {[...Array(5)].map((_, i) => (
        <div key={i} ref={(el) => { barsRef.current[i] = el; }} className="obs-visualizer-bar" />
      ))}
    </div>
  );
}
