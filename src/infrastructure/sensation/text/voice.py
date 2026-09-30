import asyncio
import io
import wave
import numpy as np
import torch
from concurrent.futures import ThreadPoolExecutor

import framework.port.sensation as sensation
import framework.core.flow as flow

# Librerie audio esterne
try:
    import pyaudio
except ImportError:
    pyaudio = None


class Adapter(sensation.Port):
    """Adapter per cattura dal microfono in tempo reale con Silero VAD per il taglio intelligente delle frasi e Faster-Whisper per la trascrizione locale."""

    capabilities = {
        "data_fusion": False,
        "anomaly_detection": False,
        "real_time_stream": True,
        "context_awareness": True,
    }

    def __init__(
        self,
        name = "mic_vad_sensation",
        whisper_model_size = "base",
        sample_rate = 16000,
        silence_threshold_sec = 0.8,
        vad_confidence = 0.5,
        **kwargs
    ):
        self.name = name
        self.whisper_model_size = whisper_model_size
        self.sample_rate = sample_rate
        self.silence_threshold_sec = silence_threshold_sec
        self.vad_confidence = vad_confidence

        self._executor = ThreadPoolExecutor(max_workers=2)
        self._is_listening = False
        self._last_context = {}
        self._kwargs = kwargs
        # Componenti ML
        self.whisper_model = None
        self.vad_model = None

    # ------------------------------------------------------------------
    # Ciclo di Vita (Start / Stop)
    # ------------------------------------------------------------------

    async def start(self, *services, **constants):
        """Carica i modelli VAD e Whisper ed emette lo start dell'adapter."""
        if pyaudio is None:
            raise RuntimeError("PyAudio non è installato. Esegui 'pip install pyaudio'")

        loop = asyncio.get_event_loop()
        
        # Caricamento asincrono dei modelli in un thread
        def _load_models():
            from faster_whisper import WhisperModel
            # 1. Carica Silero VAD tramite PyTorch Hub
            vad_model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            # 2. Carica Faster Whisper
            whisper = WhisperModel(self.whisper_model_size, device="cpu", compute_type="int8")
            return vad_model, whisper

        self.vad_model, self.whisper_model = await loop.run_in_executor(
            self._executor, _load_models
        )
        return True

    async def stop(self, *services, **constants):
        """Ferma l'ascolto e chiude l'executor."""
        self._is_listening = False
        self._executor.shutdown(wait=False)
        return True

    # ------------------------------------------------------------------
    # Algoritmo di Ascolto Continuo con Taglio Intelligente (VAD)
    # ------------------------------------------------------------------

    async def listen_for_phrase(self, *services, **constants):
        """Ascolta dal microfono e si interrompe NON appena viene rilevata la fine di una frase.
        
        Restituisce la trascrizione del blocco di testo pronunciato.
        """
        loop = asyncio.get_event_loop()
        self._is_listening = True

        # Parametri dello stream Audio
        CHUNK = 512  # Frame ottimali per Silero VAD a 16kHz
        FORMAT = pyaudio.paInt16
        CHANNELS = 1

        p = pyaudio.PyAudio()
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=CHUNK
        )

        audio_buffer = []
        is_speaking = False
        silence_chunks = 0
        max_silence_chunks = int((self.sample_rate / CHUNK) * self.silence_threshold_sec)

        try:
            while self._is_listening:
                # Legge i dati dal microfono (non bloccante per l'event loop)
                data = await loop.run_in_executor(
                    self._executor, lambda: stream.read(CHUNK, exception_on_overflow=False)
                )
                
                # Converte i byte audio in Tensor PyTorch normalizzato [-1.0, 1.0]
                audio_int16 = np.frombuffer(data, dtype=np.int16)
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                tensor_chunk = torch.from_numpy(audio_float32)

                # Calcola la probabilità che il frame contenga voce
                speech_prob = self.vad_model(tensor_chunk, self.sample_rate).item()

                if speech_prob >= self.vad_confidence:
                    if not is_speaking:
                        is_speaking = True
                        audio_buffer = []  # Inizio di una nuova frase
                    
                    audio_buffer.append(data)
                    silence_chunks = 0
                else:
                    if is_speaking:
                        audio_buffer.append(data)
                        silence_chunks += 1

                        # Se il silenzio supera la soglia, la frase è FINITA
                        if silence_chunks >= max_silence_chunks:
                            break  # Esci dal ciclo di cattura

            # Processa e trascrive il blocco audio isolato
            if audio_buffer:
                wav_bytes = self._audio_to_wav_bytes(b"".join(audio_buffer))
                return await self.perceive(*services, audio_file=wav_bytes)

        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

        return None

    # ------------------------------------------------------------------
    # Implementazione del Contratto Sensation
    # ------------------------------------------------------------------

    async def perceive(self, *services, **constants):
        """Inoltra il buffer audio catturato a Faster-Whisper per la trascrizione."""
        audio_file = constants.get("audio_file")
        if not audio_file:
            return {"status": "empty", "perceived_text": ""}

        loop = asyncio.get_event_loop()
        audio_input = io.BytesIO(audio_file) if isinstance(audio_file, bytes) else audio_file

        # Esegue la trascrizione in thread separato
        segments_gen, info = await loop.run_in_executor(
            self._executor,
            lambda: self.whisper_model.transcribe(audio_input, beam_size=3)
        )

        segments = list(segments_gen)
        full_text = " ".join([s.text for s in segments]).strip()

        perception = {
            "sensation_type": "voice_vad_perception",
            "perceived_text": full_text,
            "language": info.language,
            "duration": info.duration,
            "has_speech": len(full_text) > 0,
        }

        self._last_context = perception
        return perception

    async def process_stream(self, *services, **constants):
        return await self.listen_for_phrase(*services, **constants)

    async def evaluate_threshold(self, *services, **constants):
        return True

    async def get_context(self, *services, **constants):
        return self._last_context

    # Helper interno: converte byte grezzi PCM in formato WAV valido
    def _audio_to_wav_bytes(self, pcm_data: bytes) -> bytes:
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_data)
        return wav_io.getvalue()