# スモークテスト
- `asr.py <audio> <model> <compute_type>`: faster-whisper CPU 文字起こしの速度(RTF)確認。例: `python asr.py clip.wav kotoba-tech/kotoba-whisper-v2.0-faster float32`（int8 は出力崩壊のため不可）
- `fa.py`: torchaudio MMS_FA で文字単位の強制アライメント（DeepFilterNet3 処理後 WAV と ASR テキストを入力）。依存: torch, torchaudio, soundfile, uroman
音声・モデル・venv は含みません。
