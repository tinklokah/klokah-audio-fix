import streamlit as st
import requests
import io
import zipfile
import os
import noisereduce as nr
import librosa
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

# --- v9.1 安全後製引擎 ---
def process_audio_bytes(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.72)
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)
        intervals = detect_nonsilent(audio, min_silence_len=200, silence_thresh=-48)
        valid = [i for i in intervals if (i[1] - i[0]) > 100]
        if valid:
            min_v = min(audio[s:e].dBFS for s, e in valid)
            audio = audio + max(-2.0, min(-8.0 - min_v, 15.0))
            audio = audio.compress_dynamic_range(threshold=-7.0, ratio=8.0, attack=10.0, release=60.0)
            audio = audio + (-6.0 - audio.max_dBFS)
            audio = audio[max(0, valid[0][0]-300) : min(len(audio), valid[-1][1]+300)]
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 網頁介面 ---
st.set_page_config(page_title="族語教材直接下載器", page_icon="🚀")
st.title("🚀 繞過掃描：直接 TID 下載後製器")

st.info("由於網頁結構可能是動態生成的，我們直接輸入單元 ID (TID) 來進行下載與優化。")

# 這裡讓你手動輸入 ID，或者我們預設第一課的 ID
default_ids = "74770, 74771, 74772, 74773, 74774, 74775"
tid_input = st.text_area("請輸入要處理的 TID (用逗號隔開)", value=default_ids)

if st.button("🚀 開始直接抓取並後製"):
    tids = [t.strip() for t in tid_input.split(",") if t.strip()]
    
    if not tids:
        st.warning("請輸入至少一個 TID")
    else:
        master_zip_io = io.BytesIO()
        success_count = 0
        
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            for idx, tid in enumerate(tids):
                st.write(f"正在嘗試下載 TID: {tid}...")
                zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={tid}"
                
                try:
                    # 這裡不抓網頁，直接請求下載 API
                    res = requests.get(zip_url, timeout=20)
                    if res.status_code == 200 and len(res.content) > 500: # 確保不是抓到空檔案
                        with zipfile.ZipFile(io.BytesIO(res.content)) as sub_zip:
                            for f_name in sub_zip.namelist():
                                if f_name.lower().endswith('.mp3'):
                                    fixed = process_audio_bytes(sub_zip.read(f_name))
                                    # 存放路徑：{TID}/{檔名}
                                    master_zip.writestr(f"{tid}/{os.path.basename(f_name)}", fixed)
                        st.write(f"✅ TID {tid} 處理完成")
                        success_count += 1
                    else:
                        st.error(f"❌ TID {tid} 下載失敗 (檔案不存在或權限不足)")
                except Exception as e:
                    st.error(f"💥 TID {tid} 發生錯誤: {e}")
                
                p_bar.progress((idx + 1) / len(tids))
        
        if success_count > 0:
            st.success(f"🎉 全部處理完成！共成功處理 {success_count} 個單元。")
            st.download_button("⬇️ 下載最終優化包", master_zip_io.getvalue(), "Klokah_Direct_Fixed.zip")
        else:
            st.error("沒有任何單元被成功處理，請檢查 TID 是否正確。")
