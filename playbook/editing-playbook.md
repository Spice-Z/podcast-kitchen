# 編集プレイブック（エンドツーエンド）

パラメータの唯一の正は [config.yaml](../config.yaml)。本書・スキルに数値を書く場合は config のキー名を併記し、食い違えば config が優先。実行は `run_pipeline.sh <ep> prep …` → レビュー → `run_pipeline.sh <ep> finish`。どのステップも失敗した時点で停止する。

## 0. 素材（Zencastr）
1. Library → エピソードの ⋮ → View Tracks → 話者別 MP3 をダウンロード（ミックスではなく話者別）。文字起こしがあれば TXT。
2. ingest は元ファイルを **コピー**（移動しない）して `raw/` に置く。元素材は消さない。

## 1. 前処理（pipeline/ingest.py, sync.py, clean_*.py, level.py）
- デコード: `aresample=resampler=soxr` で 48 kHz / 24bit / mono（`ingest.*`）。LAME/Xing タグのエンコーダ遅延・パディングを読み、ギャップレス長を検証。開始オフセットを `logs/probe.json` に記録し `ingest.max_start_offset_s` 超で停止。トラック長差は `ingest.max_length_diff_s`。ffmpeg / libmp3lame のバージョンは `env.ffmpeg_version` / `env.lame_version` と一致しなければ停止。
- 同期: 最長トラックを基準に、10 ms ログエネルギー包絡（かぶり音）の相互相関。ピーク信頼度 `sync.min_peak_confidence` 未満なら補正しない。オフセット `sync.min_offset_ms`、ドリフト `sync.max_drift_ppm`（ppm）超のみ補正。
- 整音: DeepFilterNet3（`clean.dfn_atten_lim_db`）→ pedalboard（HPF → de-ess → Compressor → Limiter, `clean.*`）。afftdn は使わない。
- レベラー: 窓 `level.window_s`、ゲート `level.gate_dbfs`、最大ゲイン ±`level.max_gain_db`、平滑 `level.smoothing_s`、位置はダイナミクスの後・VAD の前。その後 `level.target_lufs` に静的ゲイン。

## 2. VAD・文字起こし・アライメント
- VAD は Silero のみ（`vad.*` 固定）。無音判定は **話者別 VAD の和集合** の一つだけ。
- 文字起こし: Zencastr の TSV（話者・発話開始時刻）を一次ソースとし、`zencastr_transcript.py` で話者トラックに割り当て、各発話を MMS_FA で整列して単語時刻を得る。kotoba ASR は既定で使わない（`asr.fallback: gaps` で未カバー区間のみ）。Zencastr からは毎回 TXT と CSV の両方を書き出す。CSV が無い場合のみ全編 ASR。
- ASR（フォールバック／CSV なし時）: kotoba-whisper-v2.0（HF revision 固定, float32, beam 5, temperature `[0.0]` のみ）。フォールバック相当（低 logprob・高圧縮率）は `logs/asr_fallbacks.json` に記録。
- 漢字→かな: fugashi + unidic-lite で分かち書き・品詞、読みは pyopenjtalk（文単位）→ uroman → MMS_FA。セグメントスコア `align.min_segment_score` 未満は `low` とし、その上の候補は review。

## 3. 編集種別（`work/candidates.json` → `labels.json` → `work/edits.json`）
`edits.json` は唯一の編集リスト: `{id, key, type, track, start, end, action(cut|duck|mute|keep|review), approved, labeler, reason, excerpt, confidence, note}`（raw 秒）。`approved: true` かつ action が review 以外のものだけが適用される。

| type | 検出 | 処理 |
|---|---|---|
| `long_pause`（長すぎる沈黙と間） | 話者別 VAD 和集合のギャップ。同一話者内 > `candidates.long_pause.within_turn_min_s`(1.2 s)、話者交代 > `between_speakers_min_s`(1.5 s) | 中央を切り `target_s`(0.7 s) を残す（タイムライン cut、ルームトーン＋クロスフェード）。直後 `laugh_lookahead_s`(2 s) 以内に笑い/反応があれば **review**（オチ前・意図的な間は詰めない） |
| `filler` | 形態素の品詞が `text.filler_pos`（フィラー/感動詞）かつ `text.fillers` に含まれ、前後に間がある。音響: テキストの無い短い VAD 島・アライナ棄却区間 | 他者無発話なら cut、他者発話中なら自トラック mute。低スコア・保護区間・音響のみは review |
| `backchannel` | `text.backchannels` のみの短い発話が他者発話中 | 10 s に 1 つ・笑いへの反応は keep、他は自トラックのみ `render.duck_db`(-20 dB) duck。タイムラインは切らない |
| `overlap_yield` | 発話開始差 ≤ `overlap_onset_s`、譲った側は直前 `yield_pre_silence_s` 無音（ターン開始）かつ島 ≤ `yield_max_s`、相手が `continue_window_s` 内に ≥ `continue_min_s` 発話 | 直後に譲り表現（`text.yield_markers`）があれば **譲った側の言いかけだけ** を自トラックで mute（ルームトーン）。無ければ review。継続話者は無傷 |
| `false_start` | かな n-gram の 2 語以内の繰り返し | 他者無発話なら cut 候補、それ以外は review |
| `crosstalk` | 2 名以上 ≥ `crosstalk_min_s` 重なり | review |
| `mistake` | `text.mistake_markers`（「ここカットで」等） | review |

自動承認は `labels.auto_approve_types` のみ。他は agent/人間のラベルが必要。

## 4. 絶対にカットしないもの
意味が変わるカット／ジョーク・笑い・その反応／冒頭・末尾 `candidates.protect_head_tail_s` 秒の内容（該当候補は review）。ブレス処理は行わない（既知の課題）。

## 5. ラベルとレビュー
- `labels.json` はキー = hash(候補 + 前後文脈)。再実行で同じ候補には同じラベルが再利用され、`seed` は既存ラベルを上書きしない。未ラベル候補があると render は停止。
- `review_export.py` → Audacity ラベル（`work/review_labels.txt`）→ 先頭に `OK`/`NG`/`cut`/`duck`/`mute`/`keep` を付けて `review_import.py`。
- 判断が数値化できないもの（意味・笑い・意図的な間）は review に回し、文章判断で自動適用しない。

## 5b. スピーチゲート（pipeline/gate.py、config `gate`）
- クリーニング・レベル調整後、各トラックを**自分の発話区間以外ではミュート**（`attenuation_db`、既定 -inf、例 -40）。発話区間 = Silero VAD ∪ 笑い ∪ 相槌（これらは決してゲートしない）。文字起こしの単語スパンは**自分の VAD 島と重なる部分だけ**を発話とみなし、VAD を超えたアライメントのにじみは捨てる（20261026 の 0:15 の鼻すすりは 6.7 秒ににじんだ単語に守られていた）。前 150 ms / 後 250 ms のパッドは単語端ではなく **VAD の発話端** 基準、300 ms 未満の隙間は結合、10–20 ms フェード。
- 過渡音（鼻すすり・咳・咳払い）の判定は **低い周期性（voicing < `voicing_max`）かつ ノイズ的な高域**（2 kHz 以上のエネルギー比 > `hb_share_min` または重心 > `centroid_min_hz`）の両方が必要。息っぽい/かすれた語尾（20261026 の「ね」の減衰は低域）は過渡音にしない。有声部から単調に下がり続ける区間（有声の減衰）はミュートしない。単語端と一致する VAD 終端の後 `word_end_keep_s` は保護。
- VAD 島の中も長さ・文字に関係なく 100 ms 窓で走査し、前後 `surround_s` に有声窓がない高域・無声窓はミュート（語中の「さ」などの摩擦音は有声に挟まれるので残る）。無声窓が `island_unvoiced_frac` 以上の島では単語を確かな支えとみなさず、`island_sniff_max_s` 以下なら島ごとミュート（20261026 の ASR 幻覚「ありがとうございました。」の上の鼻すすり）。
- 咳・咳払い（帯域に依存しない、鼻すすり判定とは別ルール `burst_*`）：確かな文字も単語トークンもない ≤ 0.6 s の島で、ノイズフロア付近（余裕 = clamp(自トラック非発話 p90 − フロア, 10, 15) dB）から 40 ms 以内に自トラック SNR × 0.4 以上立ち上がり（トラックごとに自動計算、logs/gate.json `burst_thresholds`。20261026 では host 35 dB / guest_a 26.4 dB / guest_b 30.4 dB）、ピッチが不安定（フレーム有声度中央値 < 0.5 または f0 跳び > 15%）、島全体の有声度 < 0.6（「んー」等の安定したハミングは残す）、かつ自分の有声発話終わりから ≥ 0.2 s（減衰は残す）ならミュート。20261026 の 5:20 付近の低域の咳払い（重心 約250 Hz で高域の鼻すすり判定には掛からない）が対象。
- 確かな文字（単語の半分以上がその島の中、かつ島が主に有声）がない短い VAD 島（≤ `transient_max_s`）で無声（自己相関ピーク < `voicing_max`）またはスペクトル平坦（> `flatness_min`）なもの＝鼻すすり・咳・咳払いは VAD が反応してもゲート（笑い・相槌は除く）。
- 発話区間内の過渡音検出：パッド部・結合した隙間など有声 VAD に支えられていない部分は 10 ms フレームでバースト（ノイズフロア + `transient_rise_db`）を探し、サブ窓ごとに分類して無声ならミュート。有声 VAD 島の頭/尻の無声連続 ≥ `edge_tail_min_s`（VAD に貼り付いた鼻すすり・息）もミュートし、発話側 `edge_keep_s` は残す（語末の「す」などを守る）。笑い・相槌とそのパッドは対象外。
- 全トラックがゲートされる区間は `fill_track` のルームトーンで埋め（ルームトーン窓は VAD なし かつ **バーストなし** の最も静かな窓。採取位置を `logs/gate.json` の `roomtone_source` に記録）、ミックスがデジタル無音にならないようにする。QA 指標：非発話区間のバースト数（ゲート前/後、`logs/gate.json`）。

## 6. レンダリング（pipeline/render.py）
- タイムライン cut は全トラック同時、ミックスの最小エネルギー 5 ms 点へ ±`render.snap_window_ms` でスナップ、`render.crossfade_ms` の等パワークロスフェード（全トラック同一）。
- duck/mute はトラック内のみ（`render.duck_fade_ms`）。mute はルームトーン置換。
- ルームトーン: 各トラックの VAD 外で最も静かな `render.roomtone_s` 秒窓をクロスフェードでループ。
- `work/timemap.json`（raw→編集後）を保存。出力はモノラルミックスを L/R 同一にした **デュアルモノ**。

## 7. ラウドネス（pipeline/loudness.py：唯一のラウドネスツール）
- ffmpeg loudnorm 2 パス、`linear=true`。線形にならなければ停止。予測 TP が `loudness.max_true_peak_dbtp - limiter_headroom_db` を超える場合のみ事前に alimiter。
- 目標 **-16 LUFS ±`qa.lufs_tolerance`、TP ≤ -1.0 dBTP**（納品物の MP3 を QA で測定）。

## 8. チャプター（pipeline/chapters.py）
- 再 ASR はしない。raw 文字起こしからタイトルと raw 時刻を `chapters_raw.json` に書き、timemap で編集後時刻へ変換。
- `out/chapters.json`（Podcasting 2.0）と MP3 の ID3 CHAP/CTOC を書く。`chapters.min_gap_s` 未満の間隔は停止。

## 9. QA（pipeline/qa.py）
- MP3 の LUFS・TP（クリック検査は MP3 を一時 WAV にデコードして実施、終了後削除）、先頭/末尾無音 ≤ `qa.edge_max_silence_s`（0.5 s）、クリック = ±2 ms の最大サンプル差 / 周辺 ±50 ms の中央値 > `qa.click_ratio` かつ > `qa.click_min_abs`、レベル跳び > `qa.level_jump_db`、冒頭/末尾無音、long_pause の件数・削減秒・最長残存ギャップ。`logs/qa.md` に記録、失敗で exit 1。最後に人間が通し試聴。

## 10. 納品物（リポジトリ外）
- **MP3 のみ納品**：`out/<slug>.mp3`（192 kbps CBR / 44.1 kHz stereo）と `out/chapters.json`。WAV マスターは作らない。レンダー中の一時 WAV（normalized.tmp / prelimited / mix / render/*.wav）はエンコード後に削除（`output.delete_render_wavs`）。

## 構造編集（常時適用）
- **opening_chatter**：本題開始前の雑談はカット。Zencastr 文字起こしで挨拶後に最初に番組/テーマを切り出す行（`structure.opening_chatter.start_markers`、例「今日は」「周年」「始めた」）を探し、その発話の VAD 立ち上がり − `lead_s` まで削除。外れる場合は manifest.json の `opening_chatter.start_text` に正確な行を書いて固定。カット点は前後の行を引用して報告する。
- **edge_trim**：先頭/末尾の無音は `structure.edge_silence_s`（0.3 s）まで詰める。
- ショーノート（概要・トピック・リンク・mm:ss チャプター）。リンク検索は任意で、確認していないものは **未確認** と明記。
- 種別ごとの件数と削減秒、未適用の review 一覧。アップロード・公開・送信はしない。

## リポジトリ運用（絶対ルール）
- スキル・ポリシー・config・playbook の変更はすべてこのリポジトリにコミットし、**必ず GitHub に反映する**。コミット後に sha を報告し、push 権限/承認がある環境で push する（ローカルだけに残さない）。


### overlap_restart（被って言い直し）
話者 X の短い発話（≤ `candidates.overlap_restart.max_s` = 2.0 s）に別の話者が `overlap_onset_s`（0.5 s）以内に話し始めて被り、X が `restart_window_s`（2.5 s）以内に、読み正規化した内容語（`light_words` 以外）を 1 つ以上共有するフレーズで言い直した場合、X の言いかけを **X のトラックだけ自動ミュート**。タイムラインは切らず、相手の発話は残す。auto-approve 対象で、同じ区間の overlap_yield（keep_overlap_yield で自動 keep）は出さない。後に残る間は既存の long_pause が詰める。回帰: 20261026 host 151.43–153.15「なんか最近言われてるのは」→ 154.88「最近ちょろっと聴いたのは」（guest_a 151.62–153.92 は残す）。
