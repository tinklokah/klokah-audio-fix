import streamlit as st
import requests
from bs4 import BeautifulSoup
import io
import zipfile
import re
import os
import noisereduce as nr
import librosa
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

# --- v9.1 安全後製引擎 (音質提升，檔名不動) ---
def process_audio_bytes(audio_bytes):
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
    wav_io = io.BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)
    y, sr = librosa.load(wav_io, sr=None)
    
    # 降噪 0.72
    reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.72)
    
    tmp_io = io.BytesIO()
    sf.write(tmp_io, reduced, sr, format='WAV')
    tmp_io.seek(0)
    audio = AudioSegment.from_wav(tmp_io)
    
    # 安全裁切與齊平邏輯
    intervals = detect_nonsilent(audio, min_silence_len=200, silence_thresh=-48)
    valid = [i for i in intervals if (i[1] - i[0]) > 100]
    
    if valid:
        min_v = min(audio[s:e].dBFS for s, e in valid)
        audio = audio + max(-2.0, min(-8.0 - min_v, 15.0))
        audio = audio.compress_dynamic_range(threshold=-7.0, ratio=8.0, attack=10.0, release=60.0)
        audio = audio + (-6.0 - audio.max_dBFS)
        # 保留前後 300ms
        audio = audio[max(0, valid[0][0]-300) : min(len(audio), valid[-1][1]+300)]
    
    out_io = io.BytesIO()
    audio.export(out_io, format="mp3", bitrate="192k")
    return out_io.getvalue()

# --- 網頁介面 ---
st.set_page_config(page_title="族語教材精確後製器", page_icon="🎯")
st.title("🎯 族語教材：原樣目錄與檔名後製器")

if 'lesson_list' not in st.session_state:
    st.session_state.lesson_list = []

user_id = st.text_input("1. 輸入帳號 (如: pic11304)", placeholder="pic11304")

if st.button("🔍 掃描教材清單"):
    if user_id:
        with st.spinner("掃描中..."):
            try:
                base_url = f"https://web.klokah.tw/text/main.php?user={user_id}"
                res = requests.get(base_url)
                soup = BeautifulSoup(res.text, "html.parser")
                found = []
                links = soup.find_all('a', href=re.compile(r"tid=(\d+)"))
                for l in links:
                    tid = re.search(r"tid=(\d+)", l['href']).group(1)
                    name = l.get_text(strip=True) or f"教材 {tid}"
                    if tid not in [x['tid'] for x in found]:
                        found.append({"tid": tid, "name": name})
                st.session_state.lesson_list = found
                if not found: st.error("找不到教材。")
            except Exception as e: st.error(f"錯誤：{e}")

if st.session_state.lesson_list:
    st.write("---")
    st.write("### 2. 勾選欲後製的教材 (顯示名稱方便辨識)：")
    select_all = st.checkbox("全選所有教材")
    selected = [l for l in st.session_state.lesson_list if st.checkbox(f"{l['name']} (ID: {l['tid']})", value=select_all)]

    if st.button(f"🚀 開始後製選定的 {len(selected)} 個教材"):
        if not selected:
            st.warning("請勾選教材")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                for idx, lesson in enumerate(selected):
                    st.write(f"正在處理：{lesson['tid']} ...")
                    zip_url = f"https://web.klokah.tw/text/php/downloadZip.php?tid={lesson['tid']}"
                    try:
                        z_res = requests.get(zip_url)
                        if z_res.status_code == 200:
                            with zipfile.ZipFile(io.BytesIO(z_res.content)) as sub_zip:
                                for f_name in sub_zip.namelist():
                                    if f_name.lower().endswith('.mp3'):
                                        # 執行後製
                                        fixed = process_audio_bytes(sub_zip.read(f_name))
                                        # 【絕對不變】：路徑 = TID / 原始檔名
                                        orig_name = os.path.basename(f_name)
                                        master_zip.writestr(f"{lesson['tid']}/{orig_name}", fixed)
                    except: pass
                    p_bar.progress((idx + 1) / len(selected))
            
            st.success("✨ 處理完成！資料夾與檔名皆與原站一致。")
            st.download_button("⬇️ 下載 ZIP", master_zip_io.getvalue(), f"Fixed_{user_id}.zip")
