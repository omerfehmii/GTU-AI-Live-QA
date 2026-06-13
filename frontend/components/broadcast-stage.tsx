"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, Brain, Radio, PlaySquare } from "lucide-react";

import { TypewriterText } from "@/components/typewriter-text";
import { useLiveStage } from "@/components/use-live-stage";

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

export function BroadcastStage() {
  const {
    audioLevelRef,
    audioPlaybackRef,
    playbackItem,
    speechKey,
    displayQuestion,
    visibleSpeechText,
    visibleAnswerText,
    effectiveAvatarState,
  } = useLiveStage();

  const hueRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let rafId: number;
    const update = () => {
      if (hueRef.current) {
        const level = audioLevelRef.current || 0;
        const scale = 1 + Math.min(1, Math.max(0, level * 2)) * 0.4;
        hueRef.current.style.setProperty("--vol-scale", scale.toString());
      }
      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, [audioLevelRef]);

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
