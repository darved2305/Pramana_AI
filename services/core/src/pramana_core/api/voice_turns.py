# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Voice turns inside an investigation: speak the pending question, hear the answer.

Half-duplex by design for this slice: the participant presses to talk, the clip is transcribed
with the question's context, and the transcript is extracted exactly like a typed answer.
Validation happens before any paid call, so wrong or stale requests cost nothing.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import Response

from pramana_contracts import Modality, SubmitAnswer, VoiceAnswerResult

from ..auth.deps import authorize_participant
from ..errors import ApiError
from ..investigations import InvestigationService
from ..observability import log
from ..visibility import visible_voice_answer
from ..voice.call import ParticipantCall
from ..voice.conversation import QuestionAudioCache, answer_keyterms, speak_question, stt_options
from ..voice.gnani import GnaniClient
from ..voice.media import MediaSession

router = APIRouter(prefix="/v1/investigations", tags=["voice turns"])


def _deps(request: Request) -> tuple[InvestigationService, GnaniClient, QuestionAudioCache]:
    state = request.app.state
    return state.investigations, state.gnani, state.question_audio


@router.get("/{inv_id}/questions/{question_id}/audio")
async def question_audio(inv_id: str, question_id: str, request: Request) -> Response:
    """The pending question, spoken in the participant's language (WAV)."""
    svc, gnani, cache = _deps(request)
    q = await svc.pending_question(inv_id, question_id)
    await authorize_participant(request, inv_id, q.participant.id)  # before any paid call
    audio, cached = await speak_question(gnani, cache, q.text, q.language)
    return Response(
        audio,
        media_type="audio/wav",
        headers={"X-Audio-Cached": str(cached).lower(), "Cache-Control": "no-store"},
    )


@router.websocket("/{inv_id}/questions/{question_id}/media")
async def question_media(ws: WebSocket, inv_id: str, question_id: str) -> None:
    """Live voice turn for one pending question (protocol in ``voice/media.py``)."""
    state = ws.app.state
    session = MediaSession(
        ws,
        inv_id,
        question_id,
        state.investigations,
        state.gnani,
        state.question_audio,
        state.broadcaster,
        state.media_sessions,
        state.settings.voice_max_stream_s,
    )
    await session.run()


@router.post("/{inv_id}/answers/voice")
async def voice_answer(
    inv_id: str,
    request: Request,
    question_id: Annotated[str, Form()],
    participant_id: Annotated[str, Form()],
    audio: Annotated[UploadFile, File()],
) -> VoiceAnswerResult:
    svc, gnani, _ = _deps(request)
    who = await authorize_participant(request, inv_id, participant_id)
    q = await svc.pending_question(inv_id, question_id, participant_id)
    limit: int = request.app.state.settings.voice_max_upload_bytes
    data = await audio.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "VOICE_UPLOAD_TOO_LARGE", f"audio larger than {limit} bytes")
    if not data:
        raise ApiError(422, "VOICE_EMPTY_UPLOAD", "empty audio upload")
    langs, codemix = stt_options(q.participant)
    stt = await gnani.transcribe(
        data,
        audio.filename or "answer.wav",
        langs,
        codemix=codemix,
        keyterms=answer_keyterms(q.pack, q.probe_id),
        previous_text=q.text,  # the question just asked, as recognition context (REST only)
    )
    if stt.empty:
        # Nothing heard: record nothing, keep the question pending, let the person repeat.
        raise ApiError(422, "VOICE_EMPTY_TRANSCRIPT", "no speech recognised; please repeat")
    log.info(
        "voice_answer",
        investigation_id=inv_id,
        question_id=question_id,
        detected=stt.detected_language,
        provider_ms=stt.provider_latency_ms,
    )

    async def unbiased_decode() -> str | None:
        # The same audio without the answer vocabulary or the question as context.
        alt = await gnani.transcribe(data, audio.filename or "answer.wav", langs, codemix=codemix)
        return None if alt.empty else alt.transcript

    result = await svc.answer(
        inv_id,
        SubmitAnswer(
            question_id=question_id,
            participant_id=participant_id,
            text=stt.transcript[:1000],
            modality=Modality.VOICE,
        ),
        second_decode=unbiased_decode,
    )
    return visible_voice_answer(VoiceAnswerResult(stt=stt, result=result), who)


@router.websocket("/{inv_id}/participants/{participant_id}/call")
async def participant_call(ws: WebSocket, inv_id: str, participant_id: str) -> None:
    """A participant's call: ring, consent, then every question addressed to them in turn
    (protocol in ``voice/call.py``)."""
    state = ws.app.state
    call = ParticipantCall(
        ws,
        inv_id,
        participant_id,
        state.investigations,
        state.gnani,
        state.question_audio,
        state.broadcaster,
        state.media_sessions,
        state.settings.voice_max_stream_s,
    )
    await call.run()
