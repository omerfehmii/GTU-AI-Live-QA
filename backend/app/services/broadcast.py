from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Answer,
    BroadcastPlayback,
    BroadcastSegment,
    BroadcastSegmentStatus,
    PlaybackItemKind,
    Question,
    QuestionStatus,
    SpeechJob,
    SpeechJobStatus,
    StreamSession,
    StreamStatus,
)
from app.schemas import LiveStateRead, PlaybackItemRead, QuestionRead
from app.services.speech import SpeechService


DEFAULT_AMBIENT_SEGMENTS: tuple[tuple[str, str], ...] = (
    (
        "Genel yayın akışı 1",
        "Gebze Teknik Üniversitesi tercih alanına hoş geldin. Burada üniversite seçimi, tercih süreci, kampüs yaşamı ve gelecek planların hakkında konuşabiliriz. Kararsızsan da sorun değil; bazen doğru tercih, doğru soruyu sormakla başlar.",
    ),
    (
        "Genel yayın akışı 2",
        "Üniversite tercihi sadece bir okul seçimi değildir. Aynı zamanda nasıl bir ortamda gelişmek, kimlerle çalışmak ve geleceğe nasıl hazırlanmak istediğini seçmektir. GTÜ’yü düşünüyorsan bu kararı birlikte daha net hale getirebiliriz.",
    ),
    (
        "Genel yayın akışı 3",
        "Tercih döneminde kafanın karışması çok normal. Bölüm, şehir, kampüs, ulaşım, kariyer, staj ve akademik ortam derken birçok başlık aynı anda düşünülür. Burada amacımız seçenekleri sadeleştirmek.",
    ),
    (
        "Genel yayın akışı 4",
        "GTÜ’yü değerlendirirken sadece bugüne değil, birkaç yıl sonrasına da bakmak önemli. Kendini hangi alanda geliştirmek istiyorsun, nasıl bir üniversite ortamında daha verimli olursun, bunları birlikte konuşabiliriz.",
    ),
    (
        "Genel yayın akışı 5",
        "Bir üniversiteyi tercih ederken sadece sıralamaya değil, sana ne kadar uygun olduğuna da bakmalısın. Çünkü iyi bir tercih, sadece kazanılan değil, içinde gelişebildiğin tercihtir.",
    ),
    (
        "GTÜ genel atmosfer 1",
        "GTÜ, teknik ve araştırma odaklı bir üniversite atmosferi arayan adayların dikkatini çeken bir kurumdur. Burada önemli olan yalnızca dersleri geçmek değil; düşünmek, üretmek, araştırmak ve kendini geliştirmektir.",
    ),
    (
        "GTÜ genel atmosfer 2",
        "Üniversite hayatında kampüsün sana sunduğu ortam önemlidir. Kütüphane, laboratuvarlar, akademik çalışmalar, öğrenci toplulukları ve sosyal çevre, dört yıllık deneyimin önemli parçalarıdır.",
    ),
    (
        "GTÜ genel atmosfer 3",
        "GTÜ’yü tercih listene eklemeyi düşünüyorsan kendine şu soruyu sorabilirsin: Ben teknik, bilimsel ve araştırma odaklı bir üniversite ortamında mutlu olur muyum?",
    ),
    (
        "GTÜ genel atmosfer 4",
        "Bazı öğrenciler büyük kampüs hayatını, bazıları akademik odaklı ortamları, bazıları da sektöre yakınlığı önemser. Üniversite tercihi yaparken senin için hangisinin daha öncelikli olduğunu bilmek gerekir.",
    ),
    (
        "GTÜ genel atmosfer 5",
        "Bir üniversitenin adı kadar, sana sunduğu gelişim alanları da önemlidir. GTÜ’yü değerlendirirken akademik yapı, kampüs ortamı ve gelecek hedeflerin arasında bağlantı kurabilirsin.",
    ),
    (
        "Tercih süreci 1",
        "Tercih listesi hazırlarken en sık yapılan hata, sadece puana göre karar vermektir. Puan seni bir yere götürür; ama ilgi alanın, çalışma disiplinin ve hedeflerin orada kalıcı olmanı sağlar.",
    ),
    (
        "Tercih süreci 2",
        "Tercih döneminde acele karar vermek yerine seçenekleri karşılaştırmak daha sağlıklıdır. Bir üniversiteyi seçmeden önce şehir, ulaşım, kampüs, akademik ortam ve kariyer imkanlarını birlikte düşünmek gerekir.",
    ),
    (
        "Tercih süreci 3",
        "Doğru tercih, her zaman en popüler olan tercih değildir. Doğru tercih; seni geliştiren, hedeflerine yaklaşmanı sağlayan ve kendini ait hissedebileceğin tercihtir.",
    ),
    (
        "Tercih süreci 4",
        "Üniversite seçerken şu üç soruyu kendine sorabilirsin: Burada ne öğreneceğim, nasıl gelişeceğim ve mezun olduğumda hangi yöne ilerleyebileceğim?",
    ),
    (
        "Tercih süreci 5",
        "Tercih listesinde en çok istediğin seçeneği daha üste yazmalısın. Liste sırası önemlidir; çünkü sistem seni kazanabildiğin en üst tercihe yerleştirir.",
    ),
    (
        "Konuşmaya çağrı 1",
        "İstersen buradan başlayabiliriz: Üniversitede senin için en önemli şey ne? Akademik kalite mi, şehir avantajı mı, kampüs yaşamı mı, kariyer olanakları mı?",
    ),
    (
        "Konuşmaya çağrı 2",
        "Kararsızsan sadece ilgi alanını söylemen yeterli. Sayısal alanlar mı, tasarım mı, araştırma mı, teknoloji mi, yönetim mi? Buradan birlikte ilerleyebiliriz.",
    ),
    (
        "Konuşmaya çağrı 3",
        "Puanını veya başarı sıranı biliyorsan paylaşabilirsin. Tercihlerini daha gerçekçi ve dengeli hale getirmek için birlikte değerlendirebiliriz.",
    ),
    (
        "Konuşmaya çağrı 4",
        "Üniversite seçerken kendini nerede daha rahat geliştireceğini düşünmelisin. Daha akademik bir ortam mı, daha sosyal bir kampüs mü, sektöre yakın bir konum mu sana daha uygun?",
    ),
    (
        "Konuşmaya çağrı 5",
        "GTÜ hakkında merak ettiğin tek bir konu bile varsa sorabilirsin. Kampüs, tercih süreci, ulaşım, öğrenci yaşamı ya da genel üniversite deneyimi üzerine konuşabiliriz.",
    ),
    (
        "Kısa bilgi 1",
        "Üniversite hayatı, sadece derslerden oluşmaz. Yeni insanlar tanımak, projelere katılmak, topluluklarda yer almak ve kendini farklı alanlarda denemek de bu sürecin önemli parçalarıdır.",
    ),
    (
        "Kısa bilgi 2",
        "İyi bir tercih listesi dengeli olmalıdır. Hem hayalindeki seçeneklere hem de daha gerçekçi alternatiflere yer vermek, tercih sürecini daha sağlıklı hale getirir.",
    ),
    (
        "Kısa bilgi 3",
        "Bir üniversiteyi araştırırken sadece tanıtım metinlerine değil, ders planlarına, akademik kadroya, kampüs olanaklarına ve mezunların ilerlediği alanlara da bakmak faydalıdır.",
    ),
    (
        "Kısa bilgi 4",
        "Tercih döneminde herkes fikir verebilir. Ailen, öğretmenlerin, arkadaşların yorum yapabilir. Ama son karar, senin ilgi alanların ve hedeflerinle uyumlu olmalıdır.",
    ),
    (
        "Kısa bilgi 5",
        "Bugünün dünyasında üniversite seçimi kadar, üniversite yıllarında kendini nasıl geliştirdiğin de önemlidir. Dil, yazılım, proje, staj ve iletişim becerileri her alanda fark yaratabilir.",
    ),
    (
        "Yayın havası 1",
        "Şu anda tercih döneminin en önemli sorularından birini düşünebilirsin: Ben sadece bir diploma mı istiyorum, yoksa kendimi gerçekten geliştirebileceğim bir üniversite deneyimi mi arıyorum?",
    ),
    (
        "Yayın havası 2",
        "Bazen doğru tercih, en yüksek puanlı seçenek değildir. Seni motive eden, merakını canlı tutan ve dört yıl boyunca emek verebileceğin seçenek daha doğru olabilir.",
    ),
    (
        "Yayın havası 3",
        "Üniversiteye başlamak, yeni bir şehir, yeni insanlar ve yeni bir düzen demektir. Bu yüzden tercih yaparken akademik başlıkların yanında yaşam tarzını da düşünmelisin.",
    ),
    (
        "Yayın havası 4",
        "GTÜ’yü araştırırken kendi beklentilerini de netleştirmelisin. Daha çok akademik gelişim mi arıyorsun, sektöre yakınlık mı, araştırma ortamı mı, yoksa güçlü bir teknik eğitim mi?",
    ),
    (
        "Yayın havası 5",
        "Tercih listesi yapmak bazen karmaşık görünür. Ama doğru yöntemle sadeleşir: Önce istemediklerini çıkar, sonra gerçekten ilgini çeken seçenekleri karşılaştır.",
    ),
    (
        "Motivasyon 1",
        "Kararsız olmak kötü bir şey değildir. Kararsızlık, seçenekleri ciddiye aldığını gösterir. Önemli olan bu kararsızlığı bilgiyle ve doğru sorularla azaltmaktır.",
    ),
    (
        "Motivasyon 2",
        "Üniversite tercihi hayatındaki önemli kararlardan biri olabilir; ama tek karar değildir. Kendini geliştirmeye devam ettiğin sürece seçtiğin yolu güçlendirebilirsin.",
    ),
    (
        "Motivasyon 3",
        "Bu süreçte stres yaşaman normal. Her şeyi bir anda çözmek zorunda değilsin. Önce ilgini çeken alanı, sonra üniversite ve şehir seçeneklerini düşünmek daha kolay olabilir.",
    ),
    (
        "Motivasyon 4",
        "Tercih süreci sadece sonuç odaklı değil, aynı zamanda kendini tanıma sürecidir. Neyi sevdiğini, neye emek verebileceğini ve nasıl bir gelecek istediğini keşfedersin.",
    ),
    (
        "Motivasyon 5",
        "En doğru tercih, başkalarının en çok önerdiği değil; senin hedeflerin, becerilerin ve beklentilerinle en çok örtüşen tercihtir.",
    ),
    (
        "GTÜ yönlendirme 1",
        "GTÜ’yü tercih listene eklemeyi düşünüyorsan, üniversitenin akademik yapısını, kampüs ortamını ve bulunduğu konumu birlikte değerlendirebilirsin.",
    ),
    (
        "GTÜ yönlendirme 2",
        "Teknik ve araştırma odaklı bir üniversite ortamı sana uygunsa, GTÜ hakkında daha detaylı konuşabiliriz. Hangi başlıktan başlamak istersin?",
    ),
    (
        "GTÜ yönlendirme 3",
        "Gebze Teknik Üniversitesi’ni değerlendirirken sadece üniversitenin adına değil, sana sunabileceği akademik ve kişisel gelişim alanlarına da bakmalısın.",
    ),
    (
        "GTÜ yönlendirme 4",
        "GTÜ hakkında karar verirken kendine şu soruyu sorabilirsin: Bu üniversite benim çalışma tarzıma, hedeflerime ve merak ettiğim alanlara uygun mu?",
    ),
    (
        "GTÜ yönlendirme 5",
        "Bir tercih yapmadan önce üniversiteyi tanımak önemlidir. GTÜ’nün kampüs yapısı, akademik yaklaşımı ve çevresel avantajları hakkında konuşabiliriz.",
    ),
)

LEGACY_AMBIENT_TITLES = {
    "Yayın akışı",
    "Kaynak kontrolü",
    "Sıradaki başlık",
    "Canlı ritim",
}
RETIRED_AMBIENT_TITLES = LEGACY_AMBIENT_TITLES | {
    "Tercih sohbeti",
    "Kampüs notu",
    "Hazırlık meselesi",
    "Bölüm seçimi",
    "Yayın arası",
    "Çalışma düzeni",
    "Soru beklerken",
    "Tercih taktiği",
    "Sabah ritmi",
    "Yol sohbeti",
    "Kahve molası",
    "Küçük kararlar",
    "Kampüste tempo",
    "Ders arası",
    "Telefon sessizliği",
    "Akşam planı",
    "Tercih molası",
    "Öğrenci bütçesi",
    "Kütüphane köşesi",
    "Haftalık denge",
    "Market sırası",
    "Yanlış durak",
    "Kayıp kulaklık",
    "Yağmur molası",
    "Kantin masası",
    "Eski defter",
    "Akşam otobüsü",
    "Çorba meselesi",
    "Gece mesajı",
    "Apartman ışığı",
    "Geç kalan çay",
    "Asansör sessizliği",
}


@dataclass(frozen=True)
class QueueSnapshot:
    questions: list[Question]
    size: int
    processing: Question | None
    pending: Question | None


class BroadcastService:
    RECENT_BOOTSTRAP_WINDOW = timedelta(minutes=10)
    AMBIENT_INTERRUPT_AFTER = timedelta(seconds=5)
    AMBIENT_MAX_WAIT = timedelta(seconds=12)
    AMBIENT_AUDIO_HOLD = timedelta(seconds=3)
    AMBIENT_PENDING_GRACE = timedelta(seconds=8)
    AMBIENT_PENDING_MAX_WAIT = timedelta(seconds=32)
    ANSWER_HOLD = timedelta(seconds=3.0)

    def __init__(self, db: Session, speech_service: SpeechService | None = None) -> None:
        self.db = db
        self.speech_service = speech_service or SpeechService(db)

    def live_state(self, queue_limit: int = 6) -> LiveStateRead:
        now = datetime.now(UTC)
        self._ensure_default_segments()
        playback = self._playback(now)
        queue = self._queue(queue_limit)
        playback = self._advance(playback, queue, now)

        latest_answered = self._latest_answered()
        latest_failed = self._latest_failed()
        active_streams = self.db.scalar(
            select(func.count(StreamSession.id)).where(StreamSession.status == StreamStatus.CONNECTED)
        ) or 0
        playback_item = self._playback_item(playback, now)
        current_question = self._stage_question(playback, now)
        phase = playback_item.phase if playback_item else "idle"
        avatar_state = self._avatar_state(playback, queue, latest_failed, now)

        self.db.commit()
        return LiveStateRead(
            avatar_state=avatar_state,
            current_phase=phase,
            playback_item=playback_item,
            current_question=QuestionRead.model_validate(current_question) if current_question else None,
            latest_answered=QuestionRead.model_validate(latest_answered) if latest_answered else None,
            queue=[QuestionRead.model_validate(question) for question in queue.questions],
            queue_size=queue.size,
            answer_ready_count=self._answer_ready_count(playback, now),
            speech_queue_size=self.speech_service.pending_count(),
            active_streams=int(active_streams),
            generated_at=now,
        )

    def tick(self) -> None:
        self.live_state()

    def prepare_ambient_speech_jobs(self, max_items: int | None = None) -> int:
        self._ensure_default_segments()
        if not self.speech_service.tts_available():
            self.db.flush()
            return 0

        segments = self.db.scalars(
            select(BroadcastSegment)
            .where(BroadcastSegment.status == BroadcastSegmentStatus.ACTIVE)
            .order_by(BroadcastSegment.priority.desc())
        ).all()
        prepared = 0
        for segment in segments:
            existing_job = self.speech_service.find_segment_job(
                segment,
                statuses=[
                    SpeechJobStatus.PENDING,
                    SpeechJobStatus.GENERATING,
                    SpeechJobStatus.READY,
                ],
            )
            job = self.speech_service.ensure_segment_job(segment)
            if existing_job is None and job and job.status == SpeechJobStatus.PENDING:
                prepared += 1
            if max_items is not None and prepared >= max_items:
                break

        self.db.flush()
        return prepared

    def _advance(self, playback: BroadcastPlayback, queue: QueueSnapshot, now: datetime) -> BroadcastPlayback:
        self._complete_finished_answer(playback, now)
        self._extend_active_ambient(playback, now)
        ready_question = self._next_unplayed_answer(playback, now)
        answer_ready_to_play = self._answer_ready_to_play(ready_question)

        if self._is_active(playback, now):
            if playback.kind == PlaybackItemKind.AMBIENT:
                if ready_question:
                    playback.phase = "answer_ready_waiting"
                elif queue.processing:
                    playback.phase = "preparing_answer"
                elif queue.pending:
                    playback.phase = "queue_mode"
                else:
                    playback.phase = "ambient"
            elif playback.kind == PlaybackItemKind.ANSWER:
                playback.phase = "answering"
            return playback

        if ready_question:
            if answer_ready_to_play:
                return self._start_answer(playback, ready_question, now)
            return self._start_ambient(playback, now, phase="answer_ready_waiting")
        if queue.processing:
            return self._start_ambient(playback, now, phase="preparing_answer")
        if queue.pending:
            return self._start_ambient(playback, now, phase="queue_mode")
        return self._start_ambient(playback, now, phase="ambient")

    def _start_ambient(self, playback: BroadcastPlayback, now: datetime, phase: str = "ambient") -> BroadcastPlayback:
        segment = self._select_segment(now)
        if not segment:
            playback.kind = PlaybackItemKind.IDLE
            playback.phase = "idle"
            playback.started_at = now
            playback.expected_end_at = now
            playback.can_interrupt_after = now
            playback.max_interrupt_at = now
            return playback

        job = self.speech_service.ensure_segment_job(segment)
        duration_ms = self._duration_ms(segment.content, job)
        if job and job.audio_duration_ms:
            duration_ms = min(max(duration_ms + int(self.AMBIENT_AUDIO_HOLD.total_seconds() * 1000), 6500), 52000)
        else:
            duration_ms = min(
                max(duration_ms + int(self.AMBIENT_PENDING_GRACE.total_seconds() * 1000), 9000),
                52000,
            )

        segment.last_played_at = now
        segment.play_count = (segment.play_count or 0) + 1

        playback.kind = PlaybackItemKind.AMBIENT
        playback.phase = phase
        playback.question_id = None
        playback.answer_id = None
        playback.segment_id = segment.id
        playback.speech_job_id = job.id if job else None
        playback.started_at = now
        playback.expected_end_at = now + timedelta(milliseconds=duration_ms)
        playback.can_interrupt_after = now + self.AMBIENT_INTERRUPT_AFTER
        playback.max_interrupt_at = now + self.AMBIENT_MAX_WAIT
        return playback

    def _extend_active_ambient(self, playback: BroadcastPlayback, now: datetime) -> None:
        if playback.kind != PlaybackItemKind.AMBIENT or not playback.speech_job_id:
            return

        job = self._job(playback.speech_job_id)
        if not job:
            return

        if job.status == SpeechJobStatus.READY and job.audio_duration_ms:
            audio_anchor = self._aware(playback.started_at)
            if job.updated_at:
                audio_anchor = max(audio_anchor, self._aware(job.updated_at))
            minimum_end = audio_anchor + timedelta(milliseconds=job.audio_duration_ms) + self.AMBIENT_AUDIO_HOLD
            if self._aware(playback.expected_end_at) < minimum_end:
                playback.expected_end_at = minimum_end
                playback.can_interrupt_after = max(self._aware(playback.can_interrupt_after), minimum_end)
                playback.max_interrupt_at = max(self._aware(playback.max_interrupt_at), minimum_end)
            return

        if job.status in {SpeechJobStatus.PENDING, SpeechJobStatus.GENERATING}:
            pending_deadline = self._aware(playback.started_at) + self.AMBIENT_PENDING_MAX_WAIT
            if now < pending_deadline:
                playback.expected_end_at = max(self._aware(playback.expected_end_at), min(now + timedelta(seconds=2), pending_deadline))

    def _start_answer(self, playback: BroadcastPlayback, question: Question, now: datetime) -> BroadcastPlayback:
        answer = question.answer
        if answer is None:
            return playback

        job = self.speech_service.enqueue_answer(answer)
        if (
            self.speech_service.tts_available()
            and job
            and job.status not in [SpeechJobStatus.READY, SpeechJobStatus.FAILED]
            and not answer.audio_url
        ):
            playback.phase = "answer_ready_waiting"
            return playback

        speech_text = self._answer_speech_text(answer)
        duration_ms = self._duration_ms(speech_text, job, answer=answer)
        duration_ms = min(max(duration_ms, 4500), 50000)

        playback.kind = PlaybackItemKind.ANSWER
        playback.phase = "answering"
        playback.question_id = question.id
        playback.answer_id = answer.id
        playback.segment_id = None
        playback.speech_job_id = job.id if job else None
        playback.started_at = now
        playback.expected_end_at = now + timedelta(milliseconds=duration_ms) + self.ANSWER_HOLD
        playback.can_interrupt_after = playback.expected_end_at
        playback.max_interrupt_at = playback.expected_end_at
        return playback

    def _complete_finished_answer(self, playback: BroadcastPlayback, now: datetime) -> None:
        if playback.kind != PlaybackItemKind.ANSWER or self._is_active(playback, now) or not playback.answer_id:
            return

        answer = self.db.get(Answer, playback.answer_id)
        playback.last_answer_id = playback.answer_id
        playback.last_answer_played_at = answer.created_at if answer else now

    def _playback_item(self, playback: BroadcastPlayback, now: datetime) -> PlaybackItemRead | None:
        if playback.kind == PlaybackItemKind.AMBIENT and playback.segment_id:
            segment = self.db.get(BroadcastSegment, playback.segment_id)
            if not segment:
                return None
            job = self._job(playback.speech_job_id)
            return PlaybackItemRead(
                kind="ambient",
                phase=self._phase(playback.phase),
                title=segment.title,
                text=segment.content,
                speech_key=self._speech_key(playback),
                audio_url=self._audio_url(job=job),
                audio_duration_ms=self._duration_ms(segment.content, job),
                speech_status=self._speech_status(job),
                segment_id=segment.id,
                started_at=self._aware(playback.started_at),
                expected_end_at=self._aware(playback.expected_end_at),
                can_interrupt_after=self._aware(playback.can_interrupt_after),
                max_interrupt_at=self._aware(playback.max_interrupt_at),
            )

        if playback.kind == PlaybackItemKind.ANSWER and playback.question_id and playback.answer_id:
            question = self.db.scalar(
                select(Question)
                .where(Question.id == playback.question_id)
                .options(joinedload(Question.answer))
            )
            answer = question.answer if question else self.db.get(Answer, playback.answer_id)
            if not answer:
                return None
            job = self._job(playback.speech_job_id)
            speech_text = self._answer_speech_text(answer)
            return PlaybackItemRead(
                kind="answer",
                phase="answering" if self._is_active(playback, now) else "handoff",
                title="Yanıt",
                text=speech_text,
                speech_key=self._speech_key(playback),
                audio_url=self._audio_url(answer=answer, job=job),
                audio_duration_ms=self._duration_ms(speech_text, job, answer=answer),
                speech_status=self._speech_status(job, answer=answer),
                question_id=question.id if question else None,
                answer_id=answer.id,
                started_at=self._aware(playback.started_at),
                expected_end_at=self._aware(playback.expected_end_at),
                can_interrupt_after=self._aware(playback.can_interrupt_after),
                max_interrupt_at=self._aware(playback.max_interrupt_at),
            )

        return None

    def _queue(self, limit: int) -> QueueSnapshot:
        statement = (
            select(Question)
            .options(joinedload(Question.answer))
            .where(Question.status.in_([QuestionStatus.PENDING, QuestionStatus.PROCESSING]))
            .order_by(Question.created_at.asc())
            .limit(limit)
        )
        questions = self.db.scalars(statement).unique().all()
        queue_size = self.db.scalar(
            select(func.count(Question.id)).where(Question.status.in_([QuestionStatus.PENDING, QuestionStatus.PROCESSING]))
        ) or 0
        return QueueSnapshot(
            questions=questions,
            size=int(queue_size),
            processing=next((question for question in questions if question.status == QuestionStatus.PROCESSING), None),
            pending=next((question for question in questions if question.status == QuestionStatus.PENDING), None),
        )

    def _stage_question(self, playback: BroadcastPlayback, now: datetime) -> Question | None:
        if playback.kind == PlaybackItemKind.ANSWER and playback.question_id:
            question = self.db.scalar(
                select(Question)
                .where(Question.id == playback.question_id)
                .options(joinedload(Question.answer))
            )
            if question:
                return question

        if playback.phase == "answer_ready_waiting":
            return self._next_unplayed_answer(playback, now)

        return None

    def _latest_answered(self) -> Question | None:
        return self.db.scalar(
            select(Question)
            .join(Answer)
            .options(joinedload(Question.answer))
            .where(Question.status == QuestionStatus.ANSWERED)
            .order_by(Answer.created_at.desc())
            .limit(1)
        )

    def _latest_failed(self) -> Question | None:
        return self.db.scalar(
            select(Question)
            .where(Question.status == QuestionStatus.FAILED)
            .order_by(Question.updated_at.desc())
            .limit(1)
        )

    def _next_unplayed_answer(self, playback: BroadcastPlayback, now: datetime) -> Question | None:
        threshold = playback.last_answer_played_at
        if threshold is None:
            threshold = now - self.RECENT_BOOTSTRAP_WINDOW

        statement = (
            select(Question)
            .join(Answer)
            .options(joinedload(Question.answer))
            .where(
                Question.status == QuestionStatus.ANSWERED,
                Answer.created_at > threshold,
            )
            .order_by(Answer.created_at.asc())
            .limit(1)
        )
        if playback.last_answer_id:
            statement = statement.where(Answer.id != playback.last_answer_id)
        return self.db.scalar(statement)

    def _answer_ready_count(self, playback: BroadcastPlayback, now: datetime) -> int:
        threshold = playback.last_answer_played_at
        if threshold is None:
            threshold = now - self.RECENT_BOOTSTRAP_WINDOW
        return int(
            self.db.scalar(
                select(func.count(Answer.id))
                .join(Question)
                .where(Question.status == QuestionStatus.ANSWERED, Answer.created_at > threshold)
            )
            or 0
        )

    def _select_segment(self, now: datetime) -> BroadcastSegment | None:
        segments = self.db.scalars(
            select(BroadcastSegment)
            .where(BroadcastSegment.status == BroadcastSegmentStatus.ACTIVE)
            .order_by(BroadcastSegment.priority.desc())
        ).all()
        if not segments:
            return None

        available = [
            segment
            for segment in segments
            if segment.last_played_at is None
            or now - self._aware(segment.last_played_at) >= timedelta(seconds=segment.cooldown_seconds or 0)
        ]
        candidate_segments = available or segments
        if self.speech_service.tts_available():
            ready_segments = [
                segment for segment in candidate_segments if self.speech_service.segment_audio_ready(segment)
            ]
            if ready_segments:
                candidate_segments = ready_segments

        return sorted(candidate_segments, key=self._segment_sort_key)[0]

    def _segment_sort_key(self, segment: BroadcastSegment) -> tuple[bool, datetime, int]:
        if segment.last_played_at is None:
            return (False, datetime.min.replace(tzinfo=UTC), -(segment.priority or 0))
        return (True, self._aware(segment.last_played_at), -(segment.priority or 0))

    def _playback(self, now: datetime) -> BroadcastPlayback:
        playback = self.db.get(BroadcastPlayback, "global")
        if playback:
            return playback

        playback = BroadcastPlayback(
            key="global",
            kind=PlaybackItemKind.IDLE,
            phase="idle",
            started_at=now,
            expected_end_at=now,
            can_interrupt_after=now,
            max_interrupt_at=now,
        )
        self.db.add(playback)
        self.db.flush()
        return playback

    def _ensure_default_segments(self) -> None:
        existing_segments = self.db.scalars(select(BroadcastSegment)).all()
        existing_by_title = {segment.title: segment for segment in existing_segments}
        current_titles = {title for title, _ in DEFAULT_AMBIENT_SEGMENTS}

        for segment in existing_segments:
            if segment.title in RETIRED_AMBIENT_TITLES and segment.title not in current_titles:
                segment.status = BroadcastSegmentStatus.DISABLED

        for index, (title, content) in enumerate(DEFAULT_AMBIENT_SEGMENTS):
            segment = existing_by_title.get(title)
            priority = len(DEFAULT_AMBIENT_SEGMENTS) - index
            if segment:
                segment.content = content
                segment.status = BroadcastSegmentStatus.ACTIVE
                segment.priority = priority
                segment.cooldown_seconds = 180
                continue

            self.db.add(
                BroadcastSegment(title=title, content=content, priority=priority, cooldown_seconds=180)
            )
        self.db.flush()

    def _answer_ready_to_play(self, question: Question | None) -> bool:
        if not question or not question.answer:
            return False

        answer = question.answer
        job = self.speech_service.enqueue_answer(answer)
        if answer.audio_url:
            return True
        if not self.speech_service.tts_available() or job is None:
            return True
        if job.status == SpeechJobStatus.READY and job.audio_url:
            return True
        if job.status == SpeechJobStatus.FAILED:
            return True
        return False

    def _avatar_state(
        self,
        playback: BroadcastPlayback,
        queue: QueueSnapshot,
        latest_failed: Question | None,
        now: datetime,
    ) -> str:
        recent_error = bool(
            latest_failed
            and latest_failed.updated_at
            and now - self._aware(latest_failed.updated_at) < timedelta(seconds=12)
        )
        if recent_error:
            return "error"
        if self._is_active(playback, now) and playback.kind in [PlaybackItemKind.AMBIENT, PlaybackItemKind.ANSWER]:
            return "speaking"
        if queue.processing:
            return "thinking"
        if queue.pending:
            return "listening"
        return "idle"

    def _duration_ms(self, text: str, job: SpeechJob | None, answer: Answer | None = None) -> int:
        if answer and answer.audio_duration_ms:
            return answer.audio_duration_ms
        if job and job.audio_duration_ms:
            return job.audio_duration_ms
        return self.speech_service.estimate_duration_ms(text)

    def _answer_speech_text(self, answer: Answer) -> str:
        return (answer.speech_content or answer.content).strip()

    def _audio_url(self, answer: Answer | None = None, job: SpeechJob | None = None) -> str | None:
        if answer and answer.audio_url:
            return answer.audio_url
        if job and job.status == SpeechJobStatus.READY:
            return job.audio_url
        return None

    def _speech_status(self, job: SpeechJob | None, answer: Answer | None = None) -> str:
        if answer and answer.audio_url:
            return "ready"
        if job:
            return job.status.value
        if not self.speech_service.tts_service.tts_enabled():
            return "disabled"
        return "text_only"

    def _job(self, job_id: str | None) -> SpeechJob | None:
        if not job_id:
            return None
        return self.db.get(SpeechJob, job_id)

    def _phase(self, value: str) -> str:
        allowed = {
            "idle",
            "ambient",
            "preparing_answer",
            "answer_ready_waiting",
            "handoff",
            "answering",
            "queue_mode",
            "error",
        }
        return value if value in allowed else "ambient"

    def _speech_key(self, playback: BroadcastPlayback) -> str:
        target = playback.answer_id or playback.segment_id or "none"
        return f"{playback.kind.value}:{target}:{self._aware(playback.started_at).isoformat()}"

    def _is_active(self, playback: BroadcastPlayback, now: datetime) -> bool:
        return playback.kind != PlaybackItemKind.IDLE and self._aware(playback.expected_end_at) > now

    def _aware(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
