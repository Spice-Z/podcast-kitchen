# ITトリオ 編集方針メモ（2026-10-31）

## 前提・環境
- Box: 8 vCPU / RAM 15GB（空き約7.6GB）/ GPU なし / ディスク空き 34GB / Python 3.13, ffmpeg 7.1
- 素材: Zencastr の話者別トラック（+ Zencastr 文字起こし）
- 結論: ffmpeg は「入出力・最終ラウドネス測定」に限定。整音・判断・ASR は専用ツールで行う。

## 推奨スタック（第一候補 / 代替）
| 工程 | 第一候補 | 代替 | 理由 |
|---|---|---|---|
| 同期・整列 | Zencastr トラックは同時刻開始→先頭オフセット確認のみ。ずれ時は相互相関（scipy）で補正 | audalign / ffmpeg adelay | 話者別録音なので通常ズレ小。ドリフトは長尺で要確認 |
| ノイズ・残響除去 | DeepFilterNet3（MIT/Apache, CPUリアルタイム可, 48kHz） https://github.com/Rikorose/DeepFilterNet | RNNoise（BSD, 軽量・品質低め）/ Resemble Enhance（MIT, GPU推奨, 帯域補完あり・人工感リスク） | DFN3はCPUで実用速度、音声品質評価(PESQ/DNSMOS)で高評価。VoiceFixerは劣化音源向けで過処理気味、Demucs/UVRは音楽分離向けで不要 |
| EQ・ダイナミクス | pedalboard（Spotify, GPLv3）: HPF 80Hz → de-ess(帯域コンプ) → Compressor → Limiter。必要ならLV2/VST3をpedalboardから読込 | sox / Carla+LSP/x42 LV2 | Pythonで固定パラメータ再現可能。smoke test済 |
| レベリング | 話者別に短区間RMS→ゲイン自動化（自作、pyloudnorm測定）＋軽いコンプ | Auphonic（有料API、月2h無料枠あり・購入不可のため不採用） | Auphonic相当の「Leveler」を簡易再現 |
| ラウドネス | pyloudnorm で -16 LUFS / TP -1 dBTP、ffmpeg loudnorm 2パス(linear=true)で最終 | ffmpeg loudnorm単独 | 測定→線形ゲイン→リミッタで決定的 |
| 文字起こし | faster-whisper + kotoba-whisper-v2.x（日本語特化, Apache-2.0）または large-v3-turbo を話者別トラックごとに実行（CPU float32、int8は実測で出力崩壊） | ReazonSpeech-nemo v2（Apache-2.0, 日本語高精度, CPU可） | 話者別トラック→話者ラベルは自明、pyannote不要。kotobaは日本語CER改善・高速 |
| 単語タイムスタンプ | WhisperX 方式 or ctc-forced-aligner（日本語wav2vec2/MMS）で強制アライメント | faster-whisper word_timestamps | Whisperの単語時刻は±0.2–0.5秒ずれ、カット点には強制アライメントが必要 |
| 話者分離 | 原則不要（トラック分離済）。クロストーク判定は各トラックVAD(Silero VAD, MIT)の重なりで | pyannote 3.1（MIT, HFトークン要、CPU遅い） | 混在録音時のみ使用 |
| カット判断 | 文字起こし+VAD→ルール候補（長無音>1.2s→0.5sに短縮、言い直し、フィラー「えー/あのー」の連続）→LLMで候補にラベル付け→人間レビュー → EDL(JSON) | auto-editor（無音のみ、Unlicense） | Descript型の「トランスクリプト編集」をEDLで再現。笑い・ボケは保護 |
| レンダリング | EDLをPythonで適用：ゼロクロス付近で10–30ms等パワークロスフェード、無音は削除せずルームトーンで置換、ブレスは削除せず-6〜-10dB | ffmpeg concat+acrossfade | プロのダイアログ編集手法に準拠 |
| チャプター | 編集後音声を再ASR→LLMで話題区切り→タイムスタンプ（ID3 CHAP / Podcasting 2.0 JSON） | Zencastr文字起こし+EDLの時刻変換 | 編集後音声基準で時刻ずれ防止 |
| QA | カット点ごとに前後2秒のクリップ自動書き出し＋波形/スペクトログラム画像、レベル跳び(>3dB)・クリック検出、最終LUFS/TP測定 | 人間が通しで1.5倍速確認 | 決定的チェック＋耳での最終確認 |

## 決定性（固定すべきもの）
- モデル: リポジトリ+コミットハッシュ/HF revision を固定（DFN3, kotoba-whisper, aligner, Silero VAD）
- ASR: temperature=0, beam_size=5, compute_type=float32（int8禁止・実測で崩壊）, condition_on_previous_text=False, VADパラメータ固定
- pip は lock ファイル（uv lock）で固定、torch threads 固定
- 整音パラメータ・カットルール閾値は YAML に記録、EDL・ログを保存
- LLM判断は temperature=0 + 出力（候補ラベル）をEDLとして保存し、再実行ではなく保存結果を再利用

## 人間レビュー必須
- 意味・ジョーク・相づちに関わるカット（LLM提案は全件承認制）
- クロストークの処理（片方を下げるか残すか）
- 固有名詞・技術用語の文字起こし修正、チャプタータイトル
- 最終通し試聴（特に冒頭/エンディング）

## 改訂手順
1. 取込: 各トラックを48kHz/24bit WAV化、オフセット/ドリフト確認
2. 話者別に DFN3 → pedalboard（HPF, de-ess, comp）
3. 話者別 Silero VAD + faster-whisper(kotoba) + 強制アライメント
4. カット候補生成（ルール）→ LLMラベル → 人間レビュー → EDL確定
5. EDL を全トラック同時に適用（同期維持）、クロスフェード、ルームトーン
6. 話者別レベリング → ミックス → -16 LUFS / -1 dBTP
7. 書き出し: WAVマスター(48k/24bit) + MP3 192k stereo (LAME CBR)
8. 編集後音声を再ASR → チャプター生成 → 人間確認
9. QA: カット点クリップ・レベル跳び・LUFS 測定レポート

## リスク・未決事項
- Python 3.13 では DeepFilterNet/WhisperX の依存（torch, 古い numpy）が入らない可能性 → Python 3.11 venv（uv）推奨
- CPUのみ: large-v3 は1時間音源で数十分〜1時間超。kotoba/turboで短縮
- DFN3 の過処理（笑い声・息の劣化）→ attenuation上限（例 --atten-lim 12–20dB）で調整
- Zencastr トラックのドリフト有無・サンプルレート未確認
- LLM のどのモデルを使うか、レビューUI（簡易HTML or Audacityラベル書き出し）未決
- Auphonic は品質基準として有用だが有料のため不採用（無料枠での比較も未実施）

## 追記: 実行環境の制約（Box内完結）
- 全工程をこの Linux Box（CPUのみ・8コア・15GB）で実行。ユーザーMac・Auphonic等の外部有料/クラウドAPIは使わない。
- LLMカット判断: Box上のエージェント（Grok Bot自身）がトランスクリプトを読んで候補ラベルを付ける。外部APIは呼ばない。代替は llama.cpp で小型の日本語対応モデル（Qwen 7B級 Q4、RAM約5GB）をローカル実行。
- モデル容量の目安: kotoba-whisper-v2 約1.5GB、DFN3 数十MB、Silero VAD 数MB、ctc-forced-aligner（MMS）約1.2GB。合計約3GBでディスク空き34GBに収まる。
- 処理時間の目安: 下の「検証結果」の実測値を参照（約2.2時間）


---
# 検証結果（2026-10-31 16:40–17:00 MST, Box上で実測）
テスト素材: ep491.mp3 の 600–660秒（60秒, 3人の混合音声, 48kHz mono化）。話者別トラックではない点に注意。ダウンロード総量 約3.6GB（kotoba 1.5GB, large-v3-turbo 1.6GB, MMS_FA 約1.2GB）。

## 実測値（CPU 8コア, GPU無し）
| 項目 | 結果 |
|---|---|
| DeepFilterNet3（deepfilternet pip, torch 2.0.1/torchaudio 2.0.2 CPU, Py3.11） | 60秒を5.98秒で処理, **RTF 0.10**。1時間×3トラック≒約18分 |
| kotoba-whisper-v2.0-faster, **int8** | RTF 0.20 だが **出力が崩壊**（英単語混入:「subset人以 peeled…」）→ **使用不可** |
| kotoba-whisper-v2.0-faster, **float32** | **RTF 0.51**、日本語として正しい出力（「求人以外にもなんかね教育系の…ジェーソンLD…」）。1時間×3トラック≒約1.5時間 |
| whisper large-v3-turbo, int8 | RTF 0.28 だが同様に崩壊 → CPU int8 は本環境で不可（原因未特定: ctranslate2のCPU int8か） |
| faster-whisper word_timestamps=True + kotoba | **Segfault**（find_alignment内）→ 単語時刻は別アライナで取る |
| 強制アライメント torchaudio MMS_FA + uroman（ctc-forced-aligner と同方式, torch/torchaudio 2.8 CPU） | 260文字中250文字を整列, **RTF 0.14**。文字単位の開始/終了時刻を取得（例: 求 4.78–4.98s）。精度の定量評価は未実施 |
| ctc-forced-aligner（GitHub版） | **インストール失敗**: g++ 未導入でC++拡張がビルド不可、apt も500エラー。上の torchaudio 直接実装で代替 |
| pedalboard 0.9.26 / pyloudnorm | 動作確認済（HPF→Comp→Limiter、LUFS測定） |

## 確認したリポジトリ情報（GitHub API, 2026-10-31取得）
| ツール | ライセンス | 最終push | Stars |
|---|---|---|---|
| [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) | MIT/Apache-2.0デュアル（APIはNOASSERTION表示） | 2024-10-17（**更新停止気味**, torchaudio<2.1が必須） | 4.9k |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | 2026-10-31 | 26k |
| [WhisperX](https://github.com/m-bain/whisperX) | BSD-2 | 2026-10-22 | 25k |
| [ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner) | BSD-2 | 2026-09-07 | 0.6k |
| [kotoba-whisper-v2.0](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0) | Apache-2.0 | 2024-10 | – |
| [ReazonSpeech](https://github.com/reazon-research/ReazonSpeech) | Apache-2.0 | 2026-06-10 | 0.4k |
| [pyannote-audio](https://github.com/pyannote/pyannote-audio) | MIT（モデルはHF規約同意要） | 2026-10-25 | 10.7k |
| [silero-vad](https://github.com/snakers4/silero-vad) | MIT | 2026-10-22 | 10.6k |
| [pedalboard](https://github.com/spotify/pedalboard) | GPL-3.0 | 2026-10-23 | 6.4k |
| [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) | MIT | 2026-01-04 | 0.8k |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | Unlicense | 2026-10-31 | 5.7k |
| [resemble-enhance](https://github.com/resemble-ai/resemble-enhance) | MIT | 2024-12-03（停滞） | 2.5k |
| [rnnoise](https://github.com/xiph/rnnoise) | BSD-3 | 2025-02-22 | 5.9k |

kotoba-whisper-v2.0 の公式CER（モデルカード）: CommonVoice8 9.2 / JSUT 8.4 / ReazonSpeech 11.6（large-v3 は 8.5 / 7.1 / 14.9）。会話・TV系音声では large-v3 より良く、読み上げでは劣る。パラメータ756M、large-v3比6.3倍速と公称。

## 先行事例（実際に開いて確認）
- [dougcalobrisi/erm](https://github.com/dougcalobrisi/erm): faster-whisper単語時刻＋音響検出でフィラー除去、カット点を局所エネルギー最小→ゼロクロスへスナップ、カット長に比例したクロスフェード、元録音のルームトーンをループで敷く。**レンダリング設計の手本**（英語専用）。
- [coding-with-yiqi/podcast-edit](https://github.com/coding-with-yiqi/podcast-edit/blob/main/README.md): 中国語向けローカル完結。字級時間戳→無音/言い直し/フィラー除去、0.3秒の気口を残す、意味的な編集は会話中のエージェントが担当（APIキー不要）。**本案のLLM工程と同じ構成**。
- [soanseng/podcast-use](https://github.com/soanseng/podcast-use): 単語時刻をコンパクトなMarkdownにしてLLMがEDLを生成→ffmpegでレンダ（ASRはGroq=クラウドなので本案では不採用）。
- 編集実務: [Sound On Sound](https://www.soundonsound.com/techniques/podcast-dialogue-editing-cubase)（ブレスは削除せず約-6dB、HPF約150Hz/24dB oct・de-esser）、[Pristine Podcasts](https://app.pristinepodcasts.com/blog/crossfades-podcast-editing-explained)（同一テイク5–10ms、別テイク20–40ms、等パワー、200ms以上は二重声になる）、[iZotope](https://www.izotope.com/community/blog/basics-of-room-tone-audio-editing)（ルームトーンで無音を埋める）。

## 検証を受けた方針の修正
1. ASRは **kotoba-whisper-v2.0-faster を float32** で実行（int8禁止）。決定性パラメータに compute_type=float32 を追加。
2. 単語/文字時刻は Whisper から取らず、**torchaudio MMS_FA + uroman で強制アライメント**（ctc-forced-aligner はg++導入後に再検証）。
3. DeepFilterNet3 は torch 2.0.1/torchaudio 2.0.2 の **専用venv** に隔離（ASR/アライナとは別環境）。
4. クロスフェード既定値を 10ms（同一話者）/ 30ms（話者跨ぎ）に修正、ブレスは -6dB。
5. 1時間・3トラックの処理時間見積り: DFN 約18分 + ASR 約1.5時間 + アライン 約25分 ≒ **約2.2時間**（並列化で短縮余地）。

## 未検証（要追加確認）
- 話者別トラックでの精度（今回は混合音声）。Zencastr トラックのSR/ドリフト。
- 強制アライメントの時刻精度（目視でのみ妥当、定量未評価）。
- ReazonSpeech-nemo v2 との精度比較（未インストール）。
- DFN3 の笑い声・息への影響（聴感未評価）、atten-lim の最適値。
- CPU int8 崩壊の原因（ctranslate2版・CPU命令セット依存の可能性）。
- 冒頭表の「CPUでの処理時間目安」は上記実測で置き換え。
