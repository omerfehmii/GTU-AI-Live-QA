"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useState, useTransition } from "react";

import { getJson, postJson } from "@/lib/api";
import type { Metrics, Question } from "@/lib/types";

const AvatarStage = dynamic(
  () => import("@/components/avatar-stage").then((module) => module.AvatarStage),
  {
    ssr: false,
    loading: () => (
      <div className="avatar-stage avatar-stage-loading">
        <div className="avatar-fallback">
          <p>3D avatar yukleniyor...</p>
        </div>
      </div>
    ),
  },
);

const EMPTY_METRICS: Metrics = {
  documents: 0,
  chunks: 0,
  questions_total: 0,
  questions_answered: 0,
  active_streams: 0,
  avg_latency_ms: 0,
};

const SOURCE_LABELS: Record<Question["source_type"], string> = {
  manual: "Manuel",
  youtube: "YouTube",
  web: "Web",
  pdf: "PDF",
};

const STATUS_LABELS: Record<Question["status"], string> = {
  pending: "Bekliyor",
  processing: "İşleniyor",
  answered: "Yanıtlandı",
  failed: "Hata",
};

export function HomeDashboard() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [metrics, setMetrics] = useState<Metrics>(EMPTY_METRICS);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("Canlı soru akışı izleniyor.");
  const [isPending, startTransition] = useTransition();

  async function refresh() {
    const [questionData, metricData] = await Promise.all([
      getJson<Question[]>("/questions?limit=20"),
      getJson<Metrics>("/metrics"),
    ]);
    setQuestions(questionData);
    setMetrics(metricData);
  }

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => {
      void refresh();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    startTransition(async () => {
      try {
        await postJson<Question>("/questions/manual/queue", {
          content: draft,
          author_name: "Web Demo",
        });
        setDraft("");
        setNote("Manuel soru alındı ve yayın kuyruğuna eklendi.");
        await refresh();
      } catch (error) {
        setNote(error instanceof Error ? error.message : "Soru gönderilemedi.");
      }
    });
  }

  const latestAnsweredQuestion = questions.reduce<Question | null>((latest, question) => {
    const createdAt = question.answer?.created_at;

    if (!createdAt) {
      return latest;
    }

    if (!latest) {
      return question;
    }

    const latestCreatedAt = latest.answer?.created_at ?? "";
    return new Date(createdAt).getTime() > new Date(latestCreatedAt).getTime() ? question : latest;
  }, null);
  const latestAnswerKey = latestAnsweredQuestion?.answer?.created_at ?? null;
  const latestAnswerText = latestAnsweredQuestion?.answer?.content ?? "";

  return (
    <main className="shell">
      {/* ─── Hero ─── */}
      <section className="hero animate-in">
        <div className="hero-content">
          <div className="eyebrow">
            <span>◆</span> Gebze Teknik Üniversitesi • AI Live Desk
          </div>
          <div className="hero-row">
            <div className="hero-copy-block">
              <div>
                <h1>
                  Canlı yayından gelen GTU sorularını resmi belge bağlamıyla
                  yanıtlayan demo.
                </h1>
                <p className="hero-copy">
                  Arayüz YouTube sorularını veya manuel gönderilen talepleri
                  toplar, RAG boru hattına yollar ve cevabı canlı akışta görünür
                  hale getirir.
                </p>
              </div>
              <div className="hero-actions">
                <Link className="admin-link" href="/admin">
                  ⚙ Admin konsolu
                </Link>
                <Link className="admin-link" href="/live">
                  ▶ Yayın ekranı
                </Link>
                <div className="hero-status-card">
                  <span className="hero-status-label">3D Rehber</span>
                  <strong>Avatar arayuze entegre edildi</strong>
                  <p>
                    Acilis ekraninda artik ziyaretciyi karsilayan canli bir
                    avatar alani var.
                  </p>
                </div>
              </div>
            </div>
            <div className="hero-avatar-panel">
              <AvatarStage speechKey={latestAnswerKey} speechText={latestAnswerText} />
              <div className="hero-avatar-caption">
                <span className="hero-avatar-chip">Gogus Kadraj Avatar</span>
                <p>
                  Avatar artik bas ve ust govde kadrajinda gorunuyor ve yeni
                  bir yanit geldiginde konusuyormus gibi canlaniyor.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Metrics ─── */}
      <div className="metric-grid">
        <MetricCard
          icon="📄"
          iconColor="teal"
          label="Belgeler"
          value={metrics.documents}
          delay={1}
        />
        <MetricCard
          icon="🧩"
          iconColor="orange"
          label="Chunk"
          value={metrics.chunks}
          delay={2}
        />
        <MetricCard
          icon="❓"
          iconColor="gold"
          label="Toplam soru"
          value={metrics.questions_total}
          delay={3}
        />
        <MetricCard
          icon="📡"
          iconColor="teal"
          label="Aktif stream"
          value={metrics.active_streams}
          delay={4}
        />
        <MetricCard
          icon="⚡"
          iconColor="orange"
          label="Ort. gecikme"
          value={`${Math.round(metrics.avg_latency_ms)} ms`}
          delay={5}
        />
      </div>

      {/* ─── Main Grid ─── */}
      <section className="dashboard-grid">
        {/* Left: Manual question */}
        <div className="panel panel-accent animate-in animate-in-delay-2">
          <div className="panel-head">
            <h2>Manuel soru</h2>
            <span className="live-chip">
              {isPending ? "İşleniyor" : "Hazır"}
            </span>
          </div>
          <form className="question-form" onSubmit={handleSubmit}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Örnek: Bilgisayar mühendisliği staj süreci nasıl ilerliyor?"
              rows={5}
              required
            />
            <button
              className="btn btn-primary"
              type="submit"
              disabled={isPending || draft.trim().length < 5}
            >
              {isPending ? "Gönderiliyor..." : "Kuyruğa al"}
            </button>
          </form>
          <p className="status-note">{note}</p>
        </div>

        {/* Right: Live feed */}
        <div className="panel animate-in animate-in-delay-3">
          <div className="panel-head">
            <h2>Canlı soru akışı</h2>
            <span className="subtle-note">Her 5 saniyede bir yenilenir</span>
          </div>
          <div className="feed">
            {questions.length === 0 ? (
              <EmptyState text="Henüz soru yok. Admin panelinden veri toplayıp YouTube bağlantısını açabilirsiniz." />
            ) : (
              questions.map((question, index) => (
                <QuestionCard
                  key={question.id}
                  question={question}
                  index={index}
                />
              ))
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

/* ─── Sub-Components ─── */

function MetricCard({
  icon,
  iconColor,
  label,
  value,
  delay,
}: {
  icon: string;
  iconColor: "teal" | "orange" | "gold";
  label: string;
  value: string | number;
  delay: number;
}) {
  return (
    <div className={`metric-card animate-in animate-in-delay-${delay}`}>
      <div className={`metric-icon ${iconColor}`}>{icon}</div>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}

function QuestionCard({
  question,
  index,
}: {
  question: Question;
  index: number;
}) {
  return (
    <article
      className="question-card"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="question-meta">
        <span className={`badge badge-${question.source_type}`}>
          Kaynak: {SOURCE_LABELS[question.source_type]}
        </span>
        <span className={`badge badge-${question.status}`}>
          {STATUS_LABELS[question.status]}
        </span>
        <span>{question.author_name || "Anonim"}</span>
        <span>{new Date(question.created_at).toLocaleString("tr-TR")}</span>
      </div>
      <h3>{question.content}</h3>
      <div className="answer-block">
        {question.answer ? (
          <>
            <p>{question.answer.content}</p>
            <div className="answer-meta">
              <span>
                Yanit zamani: {new Date(question.answer.created_at).toLocaleString("tr-TR")}
              </span>
            </div>
          </>
        ) : (
          <p className="status-note">Soru henüz cevaplanmadı.</p>
        )}
      </div>
    </article>
  );
}
