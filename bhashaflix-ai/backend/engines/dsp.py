"""Small, dependency-light DSP helpers (numpy only).

Used by speaker clustering and by the stereo centre-suppression separator.
Nothing here claims to be a neural model.
"""
from __future__ import annotations

import numpy as np

EPS = 1e-10


def frame_signal(x: np.ndarray, frame: int, hop: int, *, pad: bool = True) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if pad and len(x) < frame:
        x = np.pad(x, (0, frame - len(x)))
    n_frames = 1 + max(0, (len(x) - frame) // hop)
    if n_frames <= 0:
        return np.zeros((0, frame), dtype=np.float32)
    idx = np.arange(frame)[None, :] + hop * np.arange(n_frames)[:, None]
    return x[idx]


def stft(x: np.ndarray, n_fft: int = 1024, hop: int = 256, window: str = "hann") -> np.ndarray:
    """Return complex STFT of shape (frames, n_fft//2+1)."""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    w = np.hanning(n_fft + 1)[:-1].astype(np.float32) if window == "hann" else np.ones(n_fft, dtype=np.float32)
    frames = frame_signal(x, n_fft, hop)
    if frames.size == 0:
        return np.zeros((0, n_fft // 2 + 1), dtype=np.complex64)
    return np.fft.rfft(frames * w[None, :], axis=1).astype(np.complex64)


def istft(spec: np.ndarray, n_fft: int = 1024, hop: int = 256, length: int | None = None) -> np.ndarray:
    frames = np.fft.irfft(spec, n=n_fft, axis=1).astype(np.float32)
    w = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    out_len = hop * max(0, frames.shape[0] - 1) + n_fft
    out = np.zeros(out_len, dtype=np.float32)
    norm = np.zeros(out_len, dtype=np.float32)
    win_sq = w ** 2
    for i in range(frames.shape[0]):
        start = i * hop
        out[start:start + n_fft] += frames[i] * w
        norm[start:start + n_fft] += win_sq
    out /= np.maximum(norm, EPS)
    if length is not None:
        out = out[:length] if len(out) >= length else np.pad(out, (0, length - len(out)))
    return out


def mel_filterbank(n_fft: int, n_mels: int, sample_rate: int, fmin: float = 40.0, fmax: float | None = None) -> np.ndarray:
    fmax = fmax or sample_rate / 2
    mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)  # noqa: E731
    imel = lambda m: 700.0 * (10 ** (m / 2595.0) - 1.0)  # noqa: E731
    mels = np.linspace(mel(fmin), mel(fmax), n_mels + 2)
    freqs = imel(mels)
    bins = np.floor((n_fft + 1) * freqs / sample_rate).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        if center == left:
            center += 1
        if right == center:
            right += 1
        for j in range(left, min(center, fb.shape[1])):
            fb[i, j] = (j - left) / max(1, center - left)
        for j in range(center, min(right, fb.shape[1])):
            fb[i, j] = (right - j) / max(1, right - center)
    return fb


def mfcc(x: np.ndarray, sample_rate: int = 16000, n_mels: int = 26, n_ceps: int = 13, n_fft: int = 512, hop: int = 160) -> np.ndarray:
    """Return MFCC matrix (frames, n_ceps) — classic, no external library."""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if x.size < n_fft:
        x = np.pad(x, (0, n_fft - x.size))
    spec = np.abs(stft(x, n_fft=n_fft, hop=hop)) ** 2
    fb = mel_filterbank(n_fft, n_mels, sample_rate)
    mel = spec @ fb.T
    logmel = np.log(np.maximum(mel, EPS))
    dct = np.cos(np.pi / n_mels * (np.arange(n_mels)[None, :] + 0.5) * np.arange(n_ceps)[:, None])
    ceps = logmel @ dct.T
    return ceps.astype(np.float32)


def segment_embedding(x: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Speaker-ish embedding: mean+std pooled MFCC (1..13) with deltas.

    Deliberately simple and explainable: it captures vocal-tract (spectral
    envelope) and short-term dynamics, which is enough to separate distinct
    voices in a clean clip.  pyannote is used instead when installed.
    """
    if x.size == 0:
        return np.zeros(39, dtype=np.float32)
    ceps = mfcc(x, sample_rate=sample_rate, n_ceps=14)
    ceps = ceps[:, 1:]  # drop the energy coefficient -> 13 cepstra
    if ceps.shape[0] > 2:
        delta = np.diff(ceps, axis=0)
        delta = np.vstack([delta[:1], delta])
    else:
        delta = np.zeros_like(ceps)
    feat = np.concatenate([ceps.mean(axis=0), ceps.std(axis=0), delta.std(axis=0)]).astype(np.float32)
    norm = np.linalg.norm(feat)
    return feat / norm if norm > EPS else feat


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or EPS
    return float(np.dot(a, b) / denom)


def agglomerative_cluster(embeddings: np.ndarray, *, threshold: float = 0.18, max_clusters: int = 8) -> list[int]:
    """Average-linkage agglomerative clustering on cosine *distance*.

    Merges the closest pair repeatedly.  It stops when the closest remaining
    pair is further apart than `threshold`, but it keeps merging regardless of
    the threshold while more than `max_clusters` groups remain (so a noisy clip
    can never explode into dozens of "speakers").
    """
    n = len(embeddings)
    if n == 0:
        return []
    if n == 1:
        return [0]
    clusters: list[list[int]] = [[i] for i in range(n)]
    while len(clusters) > 1:
        best = (None, None, -1.0)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                sims = [
                    cosine_similarity(embeddings[a], embeddings[b])
                    for a in clusters[i]
                    for b in clusters[j]
                ]
                dist = 1.0 - float(np.mean(sims))
                if best[0] is None or dist < best[2]:
                    best = (i, j, dist)
        if best[0] is None:
            break
        if best[2] > threshold and len(clusters) <= max_clusters:
            break
        i, j, _ = best
        clusters[i].extend(clusters[j])
        del clusters[j]
    labels = [0] * n
    for label, members in enumerate(sorted(clusters, key=lambda c: min(c))):
        for member in members:
            labels[member] = label
    return labels


def apply_fade(x: np.ndarray, sample_rate: int, fade_ms: float = 8.0) -> np.ndarray:
    x = x.copy()
    n = int(sample_rate * fade_ms / 1000.0)
    n = min(n, len(x) // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def resample_linear(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if src_rate == dst_rate or x.size == 0:
        return x
    duration = x.shape[0] / float(src_rate)
    n_out = max(1, int(round(duration * dst_rate)))
    xin = np.linspace(0.0, 1.0, num=x.shape[0], endpoint=False)
    xout = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    if x.ndim == 1:
        return np.interp(xout, xin, x).astype(np.float32)
    return np.stack([np.interp(xout, xin, x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)


def rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64)) + EPS))
    return float(20.0 * np.log10(max(rms, EPS)))


def normalize_peak(x: np.ndarray, target_db: float = -1.0) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < EPS:
        return x
    target = 10 ** (target_db / 20.0)
    return (x * (target / peak)).astype(np.float32)


def db_to_linear(db: float) -> float:
    return float(10 ** (db / 20.0))
