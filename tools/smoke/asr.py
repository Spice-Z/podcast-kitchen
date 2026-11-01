import time,json,sys
from faster_whisper import WhisperModel
m=WhisperModel(sys.argv[2],device="cpu",compute_type=sys.argv[3],cpu_threads=8)
t=time.time();segs,info=m.transcribe(sys.argv[1],language="ja",chunk_length=15,condition_on_previous_text=False,word_timestamps=False,beam_size=5,temperature=0.0)
segs=list(segs);d=time.time()-t;print("asr",round(d,1),"RTF",round(d/60,3))
open("asr.txt","w").write("".join(s.text for s in segs))

for s in segs[:8]:print(round(s.start,1),round(s.end,1),s.text)
