"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { getJson, resolveBackendAssetUrl } from "@/lib/api";
import type { AvatarState, LiveState, Question } from "@/lib/types";

const AvatarStage = dynamic(
  () => import("@/components/avatar-stage").then((module) => module.AvatarStage),
  {
    ssr: false,
    loading: () => (
      <div className="broadcast-avatar-loading">
        <span>Avatar hazırlanıyor</span>
      </div>
    ),
  },
);

const EMPTY_LIVE_STATE: LiveState = {
  avatar_state: "idle",
  current_question: null,
  latest_answered: null,
  queue: [],
  queue_size: 0,
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
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioLevelRef = useRef(0);
  const audioPlaybackRef = useRef({
    currentTime: 0,
    duration: 0,
    isPlaying: false,
  });
  const lastPlayedSpeechKeyRef = useRef<string | null>(null);
  const pendingAudioKeyRef = useRef<string | null>(null);

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

  const speechKey = liveState.latest_answered?.answer?.created_at ?? null;
  const speechAudioUrl = resolveBackendAssetUrl(liveState.latest_answered?.answer?.audio_url);
  const displayQuestion = liveState.current_question ?? liveState.latest_answered;
  const displayedQuestionId = displayQuestion?.id ?? null;
  const latestAnsweredQuestionId = liveState.latest_answered?.id ?? null;
  const answerMatchesDisplayedQuestion =
    Boolean(displayedQuestionId) && displayedQuestionId === latestAnsweredQuestionId;
  const visibleAnswerQuestion = answerMatchesDisplayedQuestion ? liveState.latest_answered : null;
  const visibleAnswer = visibleAnswerQuestion?.answer?.content ?? "";
  const visibleAnswerTime = formatTime(visibleAnswerQuestion?.answer?.created_at);
  const effectiveAvatarState: AvatarState = isAudioPlaying ? "speaking" : liveState.avatar_state;

  useEffect(() => {
    if (answerMatchesDisplayedQuestion) {
      return;
    }

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
  }, [answerMatchesDisplayedQuestion, displayedQuestionId, latestAnsweredQuestionId]);

  useEffect(() => {
    if (
      liveState.avatar_state !== "speaking" ||
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
      duration: (liveState.latest_answered?.answer?.audio_duration_ms ?? 0) / 1000,
      isPlaying: false,
    };
    audio.src = speechAudioUrl;
    audio.currentTime = 0;
    audio.play().then(() => {
      pendingAudioKeyRef.current = null;
    }).catch(() => {
      pendingAudioKeyRef.current = speechKey;
    });
  }, [liveState.avatar_state, speechAudioUrl, speechKey]);

  return (
    <main className="broadcast-shell">
      <BroadcastTopBar avatarState={effectiveAvatarState} />
      <section className="broadcast-stage">
        <div className="broadcast-panel broadcast-avatar-panel">
          <div className="broadcast-avatar-zone">
            <AvatarStage
              audioDurationMs={liveState.latest_answered?.answer?.audio_duration_ms ?? null}
              audioLevelRef={audioLevelRef}
              audioPlaybackRef={audioPlaybackRef}
              speechKey={speechKey}
              speechText={visibleAnswer}
              state={effectiveAvatarState}
              theme="studio"
            />
          </div>
        </div>

        <div className="broadcast-copy-zone">
          <LiveQuestionCard question={displayQuestion} />
          <LiveAnswerCard answer={visibleAnswer} avatarState={effectiveAvatarState} answerTime={visibleAnswerTime} />
        </div>
      </section>
    </main>
  );
}

function BroadcastTopBar({
  avatarState,
}: {
  avatarState: AvatarState;
}) {
  return (
    <div className="broadcast-topbar-shell">
      <header className="broadcast-topbar">
        <div className="broadcast-brand">
          <span className={`broadcast-live-dot broadcast-live-dot-${avatarState}`} />
          <div>
            <strong>GTU AI Live QA</strong>
            <span>YouTube canlı yayın asistanı</span>
          </div>
        </div>
      </header>
    </div>
  );
}

function LiveQuestionCard({ question }: { question: Question | null }) {
  const hasQuestion = Boolean(question);
  const questionText = question?.content ?? "Canlı sohbet dinleniyor";
  const questionLengthClass =
    hasQuestion && questionText.length > 150
      ? "is-very-long"
      : hasQuestion && questionText.length > 95
        ? "is-long"
        : "";

  return (
    <div className="broadcast-panel broadcast-question-panel">
      <article className={`broadcast-question-card ${questionLengthClass} ${hasQuestion ? "" : "is-empty"}`}>
        <div className="broadcast-card-head">
          <span className="broadcast-kicker">Soru</span>
        </div>
        {hasQuestion ? <h1>{questionText}</h1> : <p className="broadcast-empty-copy">{questionText}</p>}
        {question ? <p className="broadcast-question-meta">
          {question.author_name || "Canlı yayın sohbeti"}
          {` · ${formatTime(question.created_at)}`}
        </p> : null}
      </article>
    </div>
  );
}

function LiveAnswerCard({
  answer,
  avatarState,
  answerTime,
}: {
  answer: string;
  avatarState: AvatarState;
  answerTime: string;
}) {
  const placeholder =
    avatarState === "thinking"
      ? "Kaynaklar taranıyor ve yayın yanıtı hazırlanıyor."
      : "Yanıt hazır olduğunda burada görünür";
  const displayAnswer = answer || placeholder;
  const answerLengthClass =
    displayAnswer.length > 520
      ? "is-very-long"
      : displayAnswer.length > 320
        ? "is-long"
        : "";

  return (
    <div
      className={`broadcast-panel broadcast-answer-panel ${avatarState === "speaking" ? "is-speaking" : ""}`}
    >
      <article
        className={`broadcast-answer-card ${avatarState === "speaking" ? "is-speaking" : ""} ${answer ? "" : "is-placeholder"} ${answerLengthClass}`}
      >
        <div className="broadcast-card-head">
          <span className="broadcast-kicker">Yanıt</span>
          {answerTime ? <span className="broadcast-source-chip">Saat {answerTime}</span> : null}
        </div>
        <p>{displayAnswer}</p>
      </article>
    </div>
  );
}
