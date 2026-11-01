import time,torch,torchaudio,soundfile as sf,uroman as ur,re
from torchaudio.pipelines import MMS_FA as B
text=open("asr_kotoba_f32.txt").read()
chars=[c for c in re.sub(r"[\s、。?？!！,.]","",text)]
u=ur.Uroman()
rom=[re.sub(r"[^a-z]","",u.romanize_string(c).lower()) for c in chars]
keep=[(c,r) for c,r in zip(chars,rom) if r]
w,sr=torchaudio.load("dfn_out/clip_DeepFilterNet3.wav");w=torchaudio.functional.resample(w,sr,16000)
m=B.get_model();tok=B.get_tokenizer();al=B.get_aligner()
t=time.time()
with torch.inference_mode(): em,_=m(w)
spans=al(em[0],tok([r for _,r in keep]))
d=time.time()-t;ratio=w.shape[1]/em.shape[1]/16000
print("align s",round(d,1),"RTF",round(d/60,3),"chars",len(keep),"of",len(chars))
for (c,_),s in list(zip(keep,spans))[:25]:print(c,round(s[0].start*ratio,2),round(s[-1].end*ratio,2),end=" | ")
