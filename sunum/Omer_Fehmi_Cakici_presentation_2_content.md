# AI/RAG-Based Live GTU Q&A System - Second Presentation

## Slide 1 - Cover
AI/RAG-Based Live GTU Q&A System  
Second Presentation  

CSE 496  
Ömer Fehmi Çakıcı  
Advisor: Mehmet Göktürk  
April 2026

## Slide 2 - Contents
- Progress since the first meeting
- Updated system scope and live demo objective
- Current backend and RAG implementation
- YouTube live chat pipeline and admin tools
- Broadcast UI, avatar, TTS and lip-sync work
- Evaluation results, open issues and next steps
- References

## Slide 3 - Progress Since the First Meeting
- Problem definition was narrowed from a generic QA tool to a live YouTube broadcast assistant.
- Backend RAG pipeline was implemented: ingest, archive, chunking, embeddings, retrieval and answer traces.
- Admin panel was extended for GTU source management, YouTube stream connection and runtime TTS control.
- Live broadcast screen was redesigned around a presenter avatar, active question and current answer.
- 3D avatar loading, camera framing, mouth animation and TTS synchronization were prototyped.
- Worker/service flow was tested and fixed so queued questions are processed continuously.

Image placeholder: Admin panel or live screen screenshot.

## Slide 4 - Updated Project Scope
Main line: YouTube chat -> grounded Turkish answer -> speaking live avatar.

1. Question intake: Manual or YouTube live chat messages enter the queue.
2. Grounded answer: RAG retrieves relevant GTU pages/PDF chunks before LLM generation.
3. Broadcast response: Answer is shown on the live stage and played through TTS.
4. Avatar delivery: The avatar speaks with lip movement matched to audio duration.

- The target user is no longer only a web visitor; it is also the YouTube live audience.
- The product must feel like a broadcast scene, not only a dashboard.
- Reliability requirement: do not fabricate when GTU context is weak.

## Slide 5 - Current System Architecture
Flow:
GTU Sources -> Archive & Index -> RAG Backend -> LLM / TTS -> Live Stage

Supporting paths:
- YouTube live chat enters through the worker queue.
- Admin panel controls source ingest, indexing, YouTube stream connection and TTS settings.
- FastAPI exposes live state, question, stream and admin APIs.

Key message: Implemented data path now covers ingest, retrieval, generation, speech output and live presentation.

## Slide 6 - Backend and RAG Implementation
- GTU web/PDF ingest supports seed URLs, PDF URLs, sitemap discovery and cached source archives.
- Documents are converted into chunks and indexed with embeddings for semantic retrieval.
- Retrieval combines vector similarity with keyword/string relevance and document quality penalties.
- Answer generation uses a GTU-specific system prompt and keeps source traces internally.
- Fallback behavior is implemented for missing API keys or weak context instead of fabricating details.

Current local demo snapshot:
- Documents: 6
- Chunks: 18
- Answered demo questions: 4
- Source types: Web + PDF

Image placeholder: RAG source/archive or answer trace screenshot.

## Slide 7 - Live Broadcast UI, Avatar and TTS
- The live page was redesigned as a 16:9 broadcast scene: avatar presenter on the left, question and answer on the right.
- A rigged 3D avatar is loaded in the browser and framed as a presenter portrait.
- TTS generation was integrated through OpenRouter using an OpenAI-compatible speech endpoint.
- Avatar mouth movement now follows audio timing and volume meter data instead of a fixed short animation.
- The answer remains visible until speech ends, waits briefly, then moves to the next question.
- Admin panel can enable/disable TTS for new answers.

Image placeholder: Current /live broadcast screen.

## Slide 8 - Evaluation and Current Status
A 12-question GTU evaluation set was used to check retrieval and answer behavior.

- Top-1 source hit rate: 58.3% - needs improvement
- Top-5 source hit rate: 83.3% - target-level signal
- Answer keyword hit rate: 100% - good answer coverage
- Fallback rate: 0% - all cases answered by model
- Latency: P50 10.1s / P95 18.4s - above initial target

What this means:
- Retrieval is already usable for a demo, but top-1 precision should be improved.
- The largest remaining technical risk is latency from LLM + TTS calls.
- Current system is ready for controlled demo; next phase focuses on robustness and measurement.

Image placeholder: Evaluation chart or test log screenshot.

## Slide 9 - Next Steps
- Improve retrieval ranking with broader official GTU source coverage and better page filtering.
- Optimize latency by caching common answers, tuning model choice and separating TTS timing from answer generation.
- Complete YouTube live end-to-end demo with real chat messages and duplicate protection.
- Polish avatar delivery: more natural idle motion, stable hair/material settings and better lip-sync calibration.
- Prepare final evaluation with larger question set and compare results against success criteria.
- Finalize documentation, deployment steps and final presentation demo flow.

References used in continued work:
1. Lewis et al., Retrieval-Augmented Generation, NeurIPS 2020.
2. Karpukhin et al., Dense Passage Retrieval, EMNLP 2020.
3. FastAPI, Next.js, pgvector and YouTube Data API documentation.
4. OpenRouter / OpenAI-compatible API documentation.
5. GTU official web pages and PDF documents used as system data.
