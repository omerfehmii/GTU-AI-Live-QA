"use client";

import { useEffect, useRef, useState } from "react";

import { getJson, resolveBackendAssetUrl } from "@/lib/api";
import type { AvatarState, LiveState } from "@/lib/types";

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

export type AudioPlaybackSnapshot = {
  currentTime: number;
  duration: number;
  isPlaying: boolean;
};

/**
 * Shared live-broadcast engine: polls /live/state, drives the speech audio
 * element + Web Audio meter (for lip-sync), and exposes the derived values
 * both the classic and the warm broadcast screens render.
 */
export function useLiveStage() {
  const [liveState, setLiveState] = useState<LiveState>(EMPTY_LIVE_STATE);
  const [isAudioPlaying, setIsAudioPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState("");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioLevelRef = useRef(0);
  const audioPlaybackRef = useRef<AudioPlaybackSnapshot>({
    currentTime: 0,
    duration: 0,
    isPlaying: false,
  });
  const lastPlayedSpeechKeyRef = useRef<string | null>(null);
  const pendingAudioKeyRef = useRef<string | null>(null);

  // Wall clock for the on-screen time readout.
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(
        now.toLocaleTimeString("tr-TR", {
          hour: "2-digit",
          minute: "2-digit",
        }),
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  // Poll live state.
  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const state = await getJson<LiveState>("/live/state");
        if (!cancelled) {
          setLiveState(state);
        }
      } catch {
        return;
      }
    }
    void refresh();
    const interval = setInterval(() => {
      void refresh();
    }, 1600);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Browsers block autoplay until the first user gesture; retry then.
  useEffect(() => {
    const retryAudio = () => {
      if (!pendingAudioKeyRef.current || !audioRef.current) {
        return;
      }

      audioRef.current
        .play()
        .then(() => {
          pendingAudioKeyRef.current = null;
        })
        .catch(() => undefined);
    };

    window.addEventListener("pointerdown", retryAudio);
    window.addEventListener("keydown", retryAudio);
    return () => {
      window.removeEventListener("pointerdown", retryAudio);
      window.removeEventListener("keydown", retryAudio);
    };
  }, []);

  // Audio element + Web Audio analyser that feeds the lip-sync meter.
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
  const effectiveAvatarState: AvatarState =
    isAudioPlaying || backendWantsSpeech ? "speaking" : liveState.avatar_state;

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
    audio
      .play()
      .then(() => {
        pendingAudioKeyRef.current = null;
      })
      .catch(() => {
        pendingAudioKeyRef.current = speechKey;
      });
  }, [backendWantsSpeech, playbackItem?.audio_duration_ms, speechAudioUrl, speechKey]);

  return {
    liveState,
    isAudioPlaying,
    currentTime,
    audioLevelRef,
    audioPlaybackRef,
    playbackItem,
    speechKey,
    displayQuestion,
    visibleSpeechText,
    visibleAnswerText,
    effectiveAvatarState,
  };
}
