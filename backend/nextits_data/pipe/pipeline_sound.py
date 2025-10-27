import argparse
import json
import os
import time
from pathlib import Path

import torch
import torchaudio
from pyannote.audio import Pipeline
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor


STT_BATCH_SIZE = 16  # VRAM 상황에 따라 조정


def _load_models(device):
    processor = AutoProcessor.from_pretrained("openai/whisper-large-v3")
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        "openai/whisper-large-v3",
        torch_dtype=torch.float16,
        attn_implementation="sdpa",
    ).to(device)

    try:
        model = torch.compile(model)
    except Exception as exc:  # torch.compile 미지원 환경 대응
        print(f"torch.compile failed: {exc}. Running without compilation.")

    diarization_pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token="REMOVED_SECRET",
    ).to(torch.device(device))

    return processor, model, diarization_pipeline


def _prepare_waveform(audio_path, device):
    waveform, sample_rate = torchaudio.load(audio_path)
    waveform = waveform.to(device, dtype=torch.float16)

    if sample_rate != 16000:
        resampler = torchaudio.transforms.Resample(
            orig_freq=sample_rate,
            new_freq=16000,
        ).to(device, dtype=torch.float16)
        waveform = resampler(waveform)

    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    return waveform


def _split_segments(segments, max_duration=15):
    splitted = []
    for segment in segments:
        duration = segment["end"] - segment["start"]
        if duration <= max_duration:
            splitted.append(segment)
            continue

        current_start = segment["start"]
        while current_start < segment["end"]:
            current_end = min(current_start + max_duration, segment["end"])
            splitted.append({
                "start": current_start,
                "end": current_end,
                "speaker": segment["speaker"],
            })
            current_start = current_end
    return splitted


def run_sound_pipeline(audio_path, markdown_dir=None):
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"음성/영상 파일을 찾을 수 없습니다: {audio_path}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    processor, model, diarization_pipeline = _load_models(device)

    start_time = time.time()
    waveform = _prepare_waveform(audio_path, device)

    print("Starting speaker diarization...")
    diarization = diarization_pipeline({
        "waveform": waveform.float(),
        "sample_rate": 16000,
    })
    print("Speaker diarization complete.")

    audio_duration = waveform.shape[1] / 16000
    print(f"오디오 총 길이: {audio_duration:.2f}초")

    if hasattr(diarization, "speaker_diarization"):
        annotation = diarization.speaker_diarization
    elif hasattr(diarization, "diarization"):
        annotation = diarization.diarization
    elif hasattr(diarization, "segments"):
        annotation = diarization.segments
    else:
        annotation = diarization

    segments = [{
        "start": segment.start,
        "end": segment.end,
        "speaker": speaker,
    } for segment, _, speaker in annotation.itertracks(yield_label=True)]
    segments.sort(key=lambda x: x["start"])

    complete_segments = []
    current_time = 0.0
    gap_threshold = 0.5

    for segment in segments:
        if segment["start"] > current_time + gap_threshold:
            complete_segments.append({
                "start": current_time,
                "end": segment["start"],
                "speaker": "UNKNOWN",
            })
        complete_segments.append(segment)
        current_time = segment["end"]

    if audio_duration > current_time + gap_threshold:
        complete_segments.append({
            "start": current_time,
            "end": audio_duration,
            "speaker": "UNKNOWN",
        })

    print(f"총 세그먼트 수: {len(complete_segments)}개")

    split_segments = _split_segments(complete_segments)
    print(f"STT 처리를 위해 {len(split_segments)}개의 청크로 분할됨")

    waveform_cpu = waveform.squeeze().cpu().numpy()
    waveform_len = len(waveform_cpu)
    audio_chunks = []
    segment_metadata = []

    for segment in split_segments:
        start_sample = int(segment["start"] * 16000)
        end_sample = int(segment["end"] * 16000)

        if start_sample >= waveform_len or end_sample <= start_sample + 1600:
            continue
        end_sample = min(end_sample, waveform_len)

        audio_chunks.append(waveform_cpu[start_sample:end_sample])
        segment_metadata.append(segment)

    print(f"최종 STT 청크 수: {len(audio_chunks)}개")

    transcriptions = []
    if audio_chunks:
        generate_kwargs = {
            "task": "transcribe",
            "max_new_tokens": 200,
            "num_beams": 1,
            "temperature": 0.0,
        }

        total_chunks = len(audio_chunks)
        for i in range(0, total_chunks, STT_BATCH_SIZE):
            batch_start = time.time()

            batch_chunks = audio_chunks[i:i + STT_BATCH_SIZE]
            batch_metadata = segment_metadata[i:i + STT_BATCH_SIZE]

            inputs = processor(
                batch_chunks,
                sampling_rate=16000,
                return_tensors="pt",
                padding="max_length",
                return_attention_mask=True,
            ).to(device, dtype=torch.float16)

            generated_ids = model.generate(
                input_features=inputs.input_features,
                attention_mask=inputs.attention_mask,
                **generate_kwargs,
            )

            decoded = processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            )

            for segment, text in zip(batch_metadata, decoded):
                clean_text = text.strip()
                if clean_text and not clean_text.startswith("<|"):
                    transcriptions.append({
                        "start": segment["start"],
                        "end": segment["end"],
                        "speaker": segment["speaker"],
                        "text": clean_text,
                    })

            print(
                f"  ... 배치 {i // STT_BATCH_SIZE + 1} / {-(total_chunks // -STT_BATCH_SIZE)} 완료"
                f" (청크 {i + 1}-{min(i + STT_BATCH_SIZE, total_chunks)},"
                f" 소요시간: {time.time() - batch_start:.2f}초)"
            )
            torch.cuda.empty_cache()

        print("STT 추론 완료.")

    transcriptions.sort(key=lambda x: x["start"])

    merged = []
    if transcriptions:
        current = transcriptions[0].copy()

        for next_trans in transcriptions[1:]:
            if next_trans["speaker"] == current["speaker"]:
                current["text"] += " " + next_trans["text"]
                current["end"] = next_trans["end"]
            else:
                if current["speaker"] != "UNKNOWN" or current["text"].strip():
                    merged.append(current)
                current = next_trans.copy()

        if current["speaker"] != "UNKNOWN" or current["text"].strip():
            merged.append(current)

    print("\n=== [수정됨] 화자별 텍스트 (병합됨, 시간순) ===")
    for trans in merged:
        print(f"[{trans['speaker']}] ({trans['start']:.2f}s-{trans['end']:.2f}s) {trans['text']}")

    print("\n=== [수정됨] 화자별 텍스트 (병합됨, 화자별) ===")
    speakers = {}
    for trans in merged:
        speakers.setdefault(trans["speaker"], []).append(trans)

    for speaker, items in speakers.items():
        print(f"\n[{speaker}]")
        for trans in items:
            print(f"   ({trans['start']:.2f}s-{trans['end']:.2f}s) {trans['text']}")

    print("\n=== [수정됨] 전체 텍스트 (병합됨, 시간순) ===")
    full_text = " ".join(t["text"] for t in merged if t["speaker"] != "UNKNOWN")
    print(full_text)

    total_time = time.time() - start_time
    print(f"\n{'=' * 50}")
    print(f"총 실행 시간: {total_time:.2f}초 ({total_time / 60:.2f}분)")
    print(f"오디오 길이: {audio_duration:.2f}초 ({audio_duration / 60:.2f}분)")
    print(f"오디오 길이 대비 처리 속도: {audio_duration / total_time:.2f} 배속")
    print(f"{'=' * 50}")

    markdown_output = None
    text_output = None
    if markdown_dir:
        os.makedirs(markdown_dir, exist_ok=True)
        markdown_output = Path(markdown_dir) / f"{Path(audio_path).stem}.md"

        lines = [
            f"# Transcription for {Path(audio_path).name}",
            "",
            f"- Duration: {audio_duration:.2f}s",
            f"- Generated at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}",
            "",
            "## Speaker Timeline",
            ""
        ]

        for trans in merged:
            lines.append(
                f"### {trans['speaker']} ({trans['start']:.2f}s - {trans['end']:.2f}s)"
            )
            lines.append(trans["text"])
            lines.append("")

        with open(markdown_output, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")

        print(f"마크다운 결과 저장: {markdown_output}")

    # 화자 정보 없이 전체 텍스트만 저장
    speakerless_text = "\n".join(t["text"] for t in merged if t["speaker"] != "UNKNOWN").strip()
    stt_text_dir = Path(__file__).parent.parent / 'Results' / '7.stt'
    stt_text_dir.mkdir(parents=True, exist_ok=True)
    text_output = stt_text_dir / f"{Path(audio_path).stem}.md"

    metadata_block = {
        "source_type": "stt_transcript",
        "content_origin": "audio",
        "audio_filename": Path(audio_path).name,
        "audio_path": str(Path(audio_path).resolve()),
        "duration_seconds": round(audio_duration, 2),
        "generated_at": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    }

    with open(text_output, "w", encoding="utf-8") as f:
        if speakerless_text:
            f.write(f"<!--METADATA:{json.dumps(metadata_block, ensure_ascii=False)}-->\n\n")
            f.write(speakerless_text + "\n")
        else:
            f.write(f"<!--METADATA:{json.dumps(metadata_block, ensure_ascii=False)}-->\n")

    print(f"텍스트 결과 저장(화자 구분 없음): {text_output}")

    return {
        "segments": merged,
        "full_text": full_text,
        "audio_path": audio_path,
        "markdown_path": str(markdown_output) if markdown_output else None,
        "text_path": str(text_output) if text_output else None,
        "audio_duration": audio_duration,
        "generated_at": time.time(),
    }


def main():
    parser = argparse.ArgumentParser(description="음성/영상 STT 파이프라인")
    parser.add_argument("audio_path", help="처리할 음성/영상 파일 경로")
    args = parser.parse_args()

    run_sound_pipeline(args.audio_path)


if __name__ == "__main__":
    main()