import asyncio
import io
import inspect
import sounddevice as sd
import edge_tts  # Libreria di sintesi vocale alta qualità leggera

import framework.port.actuation as actuation
import framework.core.flow as flow


class Adapter(actuation.Port):
    """Adapter di attuazione per la Sintesi Vocale (Text-to-Speech).
    
    Converte il testo fornito in audio e lo riproduce sugli altoparlanti 
    o restituisce i byte generati.
    """

    capabilities = {
        "feedback_loop": False,
        "async_execution": True,
        "emergency_stop": True,
        "protocols": ["AUDIO-OUT", "PCM", "TTS"],
    }

    def __init__(
        self,
        name = "tts_voice_actuator",
        voice = "it-IT-DiegoNeural",  # Voce italiana naturale (Edge-TTS)
        rate = "+0%",                 # Velocità (+10%, -10%, etc.)
        volume = "+0%",
        **kwargs
    ):
        self.name = name
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self._kwargs = kwargs

        self._last_state: dict = {}
        self._current_task: asyncio.Task = None

        asyncio.create_task(self.start())

    # ------------------------------------------------------------------
    # Ciclo di Vita (Start / Stop)
    # ------------------------------------------------------------------

    
    async def start(self, *services, **constants):
        """Inizializza l'adapter e annuncia l'avvio."""
       
        startup_message = constants.get(
            "startup_message",
            "Adapter vocale avviato."
        )

        # Annuncio vocale all'avvio
        await self.execute(
            text=startup_message,
            play_audio=True,
        )

        return True


    async def stop(self, *services, **constants):
        """Interrompe eventuale riproduzione audio in corso."""
        await self._stop_current_speech()
        return True

    # ------------------------------------------------------------------
    # Implementazione del Contratto Actuator.Port
    # ------------------------------------------------------------------

    async def execute(self, *services, **constants):
        """Sintetizza e legge un testo ad alta voce.
        
        Parametri accettati in **constants:
        - text / command: Il testo da pronunciare.
        - voice: Sovrascrivi temporaneamente la voce.
        - play_audio: bool (default True) se riprodurre dagli altoparlanti.
        """
        text = constants.get("text") or constants.get("command")
        voice = constants.get("voice", self.voice)
        play_audio = constants.get("play_audio", True)

        if not text:
            return {"status": "error", "message": "Nessun testo fornito per la sintesi vocale."}

        # Ferma eventuale audio ancora in riproduzione
        await self._stop_current_speech()

        try:
            # 1. Generazione dello stream di byte dell'audio sintetizzato
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=self.rate,
                volume=self.volume
            )
            
            audio_bytes = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]

            # 2. Riproduzione hardware degli altoparlanti (se richiesto)
            if play_audio and audio_bytes:
                self._current_task = asyncio.create_task(
                    self._play_audio_bytes(audio_bytes)
                )
                await self._current_task

            execution_payload = {
                "status": "success",
                "text_spoken": text,
                "voice_used": voice,
                "audio_bytes_len": len(audio_bytes)
            }
            self._last_state = execution_payload
            return execution_payload

        except Exception as e:
            return {
                "status": "error",
                "message": f"Errore durante la sintesi vocale: {str(e)}"
            }

    async def set_state(self, *services, **constants):
        """Modifica la configurazione della voce o del volume a runtime."""
        if "voice" in constants:
            self.voice = constants["voice"]
        if "rate" in constants:
            self.rate = constants["rate"]
        if "volume" in constants:
            self.volume = constants["volume"]
            
        return {
            "status": "updated",
            "voice": self.voice,
            "rate": self.rate,
            "volume": self.volume
        }

    async def get_state(self, *services, **constants):
        """Restituisce lo stato dell'ultima riproduzione e i parametri attuali."""
        return {
            "last_spoken": self._last_state,
            "current_voice": self.voice,
            "rate": self.rate,
            "volume": self.volume
        }

    async def toggle_feature(self, *services, **constants):
        """Interrompe o sblocca la riproduzione vocale."""
        enabled = constants.get("enabled", True)
        if not enabled:
            await self._stop_current_speech()
        return {"status": "success", "speaking_enabled": enabled}

    # ------------------------------------------------------------------
    # Helper interni per il playback audio
    # ------------------------------------------------------------------

    async def _play_audio_bytes(self, mp3_bytes: bytes):
        """Decodifica e riproduce i byte MP3/WAV sugli altoparlanti."""
        import miniaudio  # Oppure decodifica tramite pydub/soundfile
        
        loop = asyncio.get_event_loop()

        def _play():
            decoded = miniaudio.decode(mp3_bytes)
            sd.play(decoded.samples, decoded.sample_rate)
            sd.wait()

        await loop.run_in_executor(None, _play)

    async def _stop_current_speech(self):
        """Annulla il task di riproduzione audio in corso se l'utente interrompe."""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            sd.stop()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass