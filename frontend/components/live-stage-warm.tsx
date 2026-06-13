"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Play } from "lucide-react";

import { TypewriterText } from "@/components/typewriter-text";
import { useLiveStage } from "@/components/use-live-stage";

const AvatarStage = dynamic(
  () => import("@/components/avatar-stage").then((module) => module.AvatarStage),
  {
    ssr: false,
    loading: () => (
      <div className="lw-avatar-loading">
        <span>Yükleniyor…</span>
      </div>
    ),
  },
);

const STATUS_LABEL: Record<string, string> = {
  speaking: "Yanıtlıyor",
  thinking: "Hazırlanıyor",
  listening: "Dinliyor",
};

export function LiveStageWarm() {
  const {
    liveState,
    audioLevelRef,
    audioPlaybackRef,
    playbackItem,
    speechKey,
    displayQuestion,
    visibleSpeechText,
    visibleAnswerText,
    effectiveAvatarState,
    currentTime,
  } = useLiveStage();

  const isSpeaking = effectiveAvatarState === "speaking";
  const statusLabel = STATUS_LABEL[effectiveAvatarState] ?? "Bekleniyor";
  const queueSize = liveState.queue_size;

  return (
    <main className="lw-canvas">
      <header className="lw-header">
        <div className="lw-brand">
          <span className="lw-logo">GTÜ AI</span>
          <span className="lw-sep" />
          <span className="lw-studio">Studio</span>
        </div>
        <div className="lw-topmeta">
          <span className={`lw-live ${isSpeaking ? "speaking" : ""}`}>
            <span className="lw-livedot" />
            Canlı
          </span>
          <span className="lw-clock">{currentTime}</span>
        </div>
      </header>

      <div className="lw-body">
        <div className="lw-avatar-card">
          <div className="lw-avatar-glow" />
          <div className="lw-avatar-canvas">
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
          <div className={`lw-status ${effectiveAvatarState}`}>
            {isSpeaking ? (
              <WarmWaveform audioLevelRef={audioLevelRef} isSpeaking />
            ) : (
              <span className="lw-status-dot" />
            )}
            <span className="lw-status-text">{statusLabel}</span>
          </div>
        </div>

        <div className="lw-content">
          <div className="lw-video">
            <div className="lw-video-inner">
              <div className="lw-play">
                <Play className="lw-play-icon" />
              </div>
              <span className="lw-video-label">Video</span>
            </div>
          </div>

          <div className="lw-qa">
            <AnimatePresence mode="wait">
              {displayQuestion ? (
                <motion.div
                  key={displayQuestion.id || "q"}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
                  className="lw-qa-inner"
                >
                  <div className="lw-kicker">Soru</div>
                  <p className="lw-question">{displayQuestion.content}</p>
                  {visibleAnswerText && (
                    <p className="lw-answer">
                      <TypewriterText text={visibleAnswerText} speed={32} cursorClassName="lw-caret" />
                    </p>
                  )}
                </motion.div>
              ) : (
                <motion.div
                  key="idle"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.45 }}
                  className="lw-qa-inner lw-qa-idle"
                >
                  <div className="lw-kicker">Yayın</div>
                  <p className="lw-idle">Yeni soru bekleniyor…</p>
                </motion.div>
              )}
            </AnimatePresence>

            <div className="lw-foot">
              {queueSize > 0 ? `Sırada ${queueSize} soru · ` : ""}GTÜ bölüm kataloğu
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

function WarmWaveform({
  audioLevelRef,
  isSpeaking,
}: {
  audioLevelRef: React.MutableRefObject<number>;
  isSpeaking: boolean;
}) {
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    let rafId: number;
    const update = () => {
      const baseLevel = audioLevelRef.current || 0;
      barsRef.current.forEach((bar, i) => {
        if (!bar) return;
        if (!isSpeaking) {
          bar.style.transform = "scaleY(0.22)";
          return;
        }
        // Gentle animated baseline so it reads as a waveform even when the
        // audio meter is momentarily silent, instead of collapsing to dots.
        const wobble = 0.36 + Math.sin(Date.now() / 200 + i * 0.8) * 0.22;
        const level = Math.max(wobble, Math.min(1, baseLevel * 2));
        bar.style.transform = `scaleY(${level})`;
      });
      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, [audioLevelRef, isSpeaking]);

  return (
    <div className={`lw-wave ${isSpeaking ? "active" : ""}`}>
      {[...Array(4)].map((_, i) => (
        <div
          key={i}
          ref={(el) => {
            barsRef.current[i] = el;
          }}
          className="lw-wave-bar"
        />
      ))}
    </div>
  );
}
