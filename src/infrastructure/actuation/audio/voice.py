"""
framework.adapter.actuation.audio
=================================

Adapter TTS per output audio.

Backend supportati:
- paplay      -> PulseAudio / PipeWire
- sounddevice -> PortAudio

Il backend ``paplay`` è preferito su Linux quando l'audio passa
attraverso PulseAudio/PipeWire, ad esempio in sessioni RDP.

Dipendenze:
    edge-tts
    miniaudio

Opzionali:
    sounddevice
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from typing import Any, cast

import edge_tts
import miniaudio

import framework.core.flow as flow
import framework.port.actuation as actuation


class Adapter(actuation.Port):
    """
    Text-to-Speech audio actuator.
    """

    capabilities = {
        "feedback_loop": False,
        "async_execution": True,
        "emergency_stop": True,
        "startup_announcement": True,
        "protocols": [
            "AUDIO-OUT",
            "PCM",
            "TTS",
        ],
        "backends": [
            "paplay",
            "sounddevice",
        ],
    }

    def __init__(
        self,
        name="tts_voice_actuator",
        voice="it-IT-ElsaNeural",
        rate="+0%",
        volume="+0%",
        announce_start=True,
        audio_backend="paplay",
        **kwargs,
    ):
        self.name = name
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.announce_start = announce_start

        # auto | paplay | sounddevice
        self.audio_backend = audio_backend

        self._kwargs = kwargs
        self._last_state: dict[str, Any] = {}
        self._current_task: asyncio.Task | None = None

        self._speaking_enabled = True
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @flow.result(inputs=("session", "actuator"))
    async def start(self, session) -> bool:
        """
        Avvia l'adapter.

        Se ``announce_start`` è attivo, pronuncia il messaggio iniziale.
        """

        if self._started:
            return True

        self._started = True

        if not self.announce_start:
            return True

        if not self._speaking_enabled:
            return True

        startup_message = "Ciao! Sono il tuo assistente virtuale. "

        if not startup_message:
            return True

        result = await self.execute(
            text=startup_message,
            play_audio=True,
        )

        if flow.is_result(result):
            result = flow.unwrap(result)

        return isinstance(result, dict) and result.get("status") == "success"

    @flow.result(inputs=("session", "actuator"))
    async def stop(
        self,
        *services: Any,
        **constants: Any,
    ) -> bool:
        """
        Ferma l'eventuale riproduzione audio.
        """

        await self._stop_current_speech()

        self._started = False

        return True

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @flow.result(inputs=("session", "actuator"))
    async def execute(
        self,
        *services: Any,
        **constants: Any,
    ) -> dict[str, Any]:
        """
        Sintetizza e riproduce il testo.

        Parametri supportati:

            text
            command
            voice
            rate
            volume
            play_audio
            audio_backend
        """

        text = (
            constants.get("text")
            or constants.get("command")
        )

        voice = constants.get(
            "voice",
            self.voice,
        )

        rate = constants.get(
            "rate",
            self.rate,
        )

        volume = constants.get(
            "volume",
            self.volume,
        )

        play_audio = constants.get(
            "play_audio",
            True,
        )

        backend = constants.get(
            "audio_backend",
            self.audio_backend,
        )

        if not text:
            return {
                "status": "error",
                "message": (
                    "Nessun testo fornito "
                    "per la sintesi vocale."
                ),
            }

        if not self._speaking_enabled:
            return {
                "status": "disabled",
                "message": (
                    "Sintesi vocale disabilitata."
                ),
            }

        await self._stop_current_speech()

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
                volume=volume,
            )

            audio_bytes = bytearray()

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes.extend(
                        chunk["data"]
                    )

            audio_bytes = bytes(audio_bytes)

            if not audio_bytes:
                return {
                    "status": "error",
                    "message": (
                        "Edge-TTS non ha prodotto audio."
                    ),
                }

            if play_audio:
                await self._play_audio_bytes(
                    audio_bytes,
                    backend=backend,
                )

            execution_payload = {
                "status": "success",
                "text_spoken": text,
                "voice_used": voice,
                "rate_used": rate,
                "volume_used": volume,
                "audio_bytes_len": len(audio_bytes),
                "audio_played": play_audio,
                "audio_backend": backend,
            }

            self._last_state = execution_payload

            return execution_payload

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            error = {
                "status": "error",
                "message": (
                    "Errore durante la sintesi vocale: "
                    f"{exc}"
                ),
                "audio_backend": backend,
            }

            self._last_state = error

            return error

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    async def _play_audio_bytes(
        self,
        mp3_bytes: bytes,
        *,
        backend: str = "paplay",
    ) -> None:
        """
        Decodifica MP3 -> PCM e riproduce l'audio.

        ``paplay``:
            usa direttamente PulseAudio/PipeWire.

        ``sounddevice``:
            usa PortAudio.
        """

        if not mp3_bytes:
            return

        loop = asyncio.get_running_loop()

        decoded = miniaudio.decode(mp3_bytes)

        if not decoded.samples:
            raise RuntimeError(
                "La decodifica non ha prodotto samples."
            )

        if backend == "auto":
            backend = self._detect_audio_backend()

        if backend == "paplay":
            await loop.run_in_executor(
                None,
                self._play_with_paplay,
                decoded,
            )

        elif backend == "sounddevice":
            await loop.run_in_executor(
                None,
                self._play_with_sounddevice,
                decoded,
            )

        else:
            raise ValueError(
                f"Backend audio non supportato: "
                f"{backend!r}. "
                "Usare 'paplay', 'sounddevice' "
                "oppure 'auto'."
            )

    # ------------------------------------------------------------------
    # paplay
    # ------------------------------------------------------------------

    @staticmethod
    def _play_with_paplay(decoded: Any) -> None:
        """
        Riproduce PCM tramite PulseAudio/PipeWire.

        Non utilizza PortAudio e quindi non dipende
        dall'enumerazione dei device di sounddevice.
        """

        paplay = shutil.which("paplay")

        if not paplay:
            raise RuntimeError(
                "Comando 'paplay' non trovato. "
                "Installare pulseaudio-utils."
            )

        sample_width = decoded.sample_width

        if sample_width in (1, 2):
            sample_format = "s16le"
        elif sample_width == 4:
            sample_format = "s32le"
        else:
            raise RuntimeError(
                "Sample width non supportato da paplay: "
                f"{sample_width} bytes"
            )

        command = [
            paplay,
            "--raw",
            f"--rate={decoded.sample_rate}",
            f"--channels={decoded.nchannels}",
            f"--format={sample_format}",
        ]

        process = subprocess.run(
            command,
            input=bytes(decoded.samples),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        if process.returncode != 0:
            stderr = (
                process.stderr.decode(
                    "utf-8",
                    errors="replace",
                ).strip()
            )

            raise RuntimeError(
                "paplay ha restituito "
                f"exit code {process.returncode}: "
                f"{stderr}"
            )

    # ------------------------------------------------------------------
    # sounddevice
    # ------------------------------------------------------------------

    @staticmethod
    def _play_with_sounddevice(
        decoded: Any,
    ) -> None:
        """
        Backend PortAudio/sounddevice.
        """

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice non è installato."
            ) from exc

        sd.play(
            decoded.samples,
            decoded.sample_rate,
        )

        sd.wait()

    # ------------------------------------------------------------------
    # Backend detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_audio_backend() -> str:
        """
        Determina automaticamente il backend.

        Priorità:
            1. paplay
            2. sounddevice
        """

        if shutil.which("paplay"):
            return "paplay"

        try:
            import sounddevice as sd

            devices = sd.query_devices()

            if devices:
                return "sounddevice"

        except Exception:
            pass

        raise RuntimeError(
            "Nessun backend audio disponibile. "
            "Installare paplay/pulseaudio-utils "
            "oppure sounddevice."
        )

    # ------------------------------------------------------------------
    # Speech control
    # ------------------------------------------------------------------

    async def _stop_current_speech(self) -> None:
        """
        Ferma l'eventuale task di sintesi/riproduzione.
        """

        task = self._current_task

        if task is None:
            return

        if task.done():
            self._current_task = None
            return

        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._current_task = None

    def enable_speech(self) -> None:
        """
        Abilita la sintesi vocale.
        """

        self._speaking_enabled = True

    def disable_speech(self) -> None:
        """
        Disabilita la sintesi vocale.
        """

        self._speaking_enabled = False

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @flow.result(inputs=("session", "actuator"))
    async def set_state(
        self,
        session: Any = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        """
        Aggiorna lo stato dell'adapter.
        """

        if state is None and isinstance(session, dict):
            state = cast(dict[str, Any], session)

        if not isinstance(state, dict):
            raise TypeError(
                "state deve essere un dict."
            )

        self._last_state.update(state)

    @flow.result(inputs=("session", "actuator"))
    async def get_state(self, session: Any = None) -> dict[str, Any]:
        """
        Restituisce l'ultimo stato.
        """

        return {
            **self._last_state,
            "name": self.name,
            "voice": self.voice,
            "rate": self.rate,
            "volume": self.volume,
            "audio_backend": self.audio_backend,
            "speaking_enabled": (
                self._speaking_enabled
            ),
            "started": self._started,
        }

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_backend(
        self,
        backend: str,
    ) -> None:
        """
        Cambia il backend audio.

        Valori:
            paplay
            sounddevice
            auto
        """

        valid = {
            "paplay",
            "sounddevice",
            "auto",
        }

        if backend not in valid:
            raise ValueError(
                f"Backend non valido: {backend!r}. "
                f"Valori supportati: {sorted(valid)}"
            )

        self.audio_backend = backend

    # ------------------------------------------------------------------
    # Feature
    # ------------------------------------------------------------------

    @flow.result(inputs=("session", "actuator"))
    async def toggle_feature(
        self,
        session: Any = None,
        feature_name: str | bool | None = None,
        enabled: bool | None = None,
        **constants: Any,
    ) -> bool:
        """
        Abilita/disabilita una feature dell'adapter.

        Feature supportate:
            speech
            tts
            speaking
            startup_announcement

        Se ``enabled`` è None, la feature viene invertita.

        Ritorna lo stato finale.
        """

        if isinstance(session, str) and (
            feature_name is None or isinstance(feature_name, bool)
        ):
            if isinstance(feature_name, bool):
                enabled = feature_name
            feature_name = session

        if feature_name is None:
            feature_name = constants.get("feature")

        if not isinstance(feature_name, str):
            raise ValueError(
                f"Feature non supportata: {feature_name!r}. "
                "Feature disponibili: "
                "'speech', 'tts', 'speaking', "
                "'startup_announcement'."
            )

        aliases = {
            "speech": "speech",
            "tts": "speech",
            "speaking": "speech",
            "startup_announcement": "startup_announcement",
        }

        feature_name = aliases.get(
            feature_name,
            feature_name,
        )

        if feature_name == "speech":
            if enabled is None:
                enabled = not self._speaking_enabled

            self._speaking_enabled = bool(enabled)

            return self._speaking_enabled

        if feature_name == "startup_announcement":
            if enabled is None:
                enabled = not self.announce_start

            self.announce_start = bool(enabled)

            return self.announce_start

        raise ValueError(
            f"Feature non supportata: {feature_name!r}. "
            "Feature disponibili: "
            "'speech', 'tts', 'speaking', "
            "'startup_announcement'."
        )