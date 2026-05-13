import streamlit as st
import requests
import io
import os
import zipfile
import subprocess
import librosa
import soundfile as sf
import noisereduce as nr
import time
from pydub import AudioSegment, effects
from pydub.silence import detect_nonsilent

# --- 核心優化：移植自 audio_bot_gui.py 的專業邏輯 ---
def process_audio_pro(audio_bytes, filename):
    timestamp = int(time.time() * 1000)
    temp_input = f"temp_in_{timestamp}.mp3"
    temp_norm = f"temp_norm_{timestamp}.wav"
    temp_clean = f"temp_clean_{timestamp}.wav"
    
    try:
        # 儲存原始檔案以供 FFmpeg 讀取
        with open(temp_input, "wb") as f:
            f.write(audio_bytes)

        # 1. 執行 loudnorm (建立厚度與基本響度)
        # 比照原程式：I=-18 (響度), TP=-6 (峰值), LRA=3 (厚實感)
        cmd = [
            "ffmpeg", "-y", "-i", temp_input,
            "-af", "loudnorm=I=-18:TP=-6:LRA=3", 
            "-ar", "44100", temp_norm
        ]
        # 注意：Streamlit 雲端環境需有 ffmpeg，如果是本地執行請確保路徑正確
        subprocess.run(cmd, check=True, capture_output=True)

        # 2. AI 降噪 (移植原程式參數: 0.75)
        y, sr = librosa.load(temp_norm, sr=None)
        reduced_noise = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        sf.write(temp_clean, reduced_noise, sr)

        # 3. 讀入 Pydub 進行「強制峰值調整」與「去頭尾」
        audio = AudioSegment.from_wav(temp_clean)
        
        # 強制最高峰推到 -6dB (headroom=6.0)
        audio = effects.normalize(audio, headroom=6.0)

        # 4. 去頭尾裁切 (原程式參數：前後保留 200ms)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            start_trim = max(0, intervals[0][0] - 200)
            end_trim = min(len(audio), intervals[-1][1] + 200)
            audio = audio[start_trim:end_trim]

        # 5. 輸出轉為 Bytes
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()

    except Exception as e:
        st.error(f"處理失敗 ({filename}): {e}")
        return audio_bytes
    finally:
        # 清理暫存檔
        for t in [temp_input, temp_norm, temp_clean]:
            if os.path.exists(t):
                os.remove(t)

# --- 網頁介面 (保持原本的 API 抓取與分類邏輯) ---
st.set_page_config(page_title="族語 AI 專業版", page_icon="🎙️", layout="wide")
st.title("🎙️ 族語全自動：AI 專業處理版 (v3.6 核心移植)")

user_id = st.text_input("輸入帳號 ID", value="picex11301")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []

if st.button("🔍 1. 抓取清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        tasks = []
        def scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        folder = v.split('/')[-2] if len(v.split('/')) >= 2 else "其他"
                        tasks.append({"url": full_url, "folder": folder, "file": os.path.basename(v)})
                        if f"chk_{full_url}" not in st.session_state: st.session_state[f"chk_{full_url}"] = True
                    else: scan(v)
            elif isinstance(obj, list):
                for i in obj: scan(i)
        scan(data)
        st.session_state.audio_tasks = tasks
        st.success(f"找到 {len(tasks)} 個檔案，已就緒。")
    except: st.error("連線 API 失敗")

# --- 選擇與批次處理 ---
if st.session_state.audio_tasks:
    grouped = {}
    for t in st.session_state.audio_tasks: grouped.setdefault(t['folder'], []).append(t)
    
    st.write("---")
    c_g1, c_g2, _ = st.columns([1, 1, 8])
    if c_g1.button("🌐 全部全選"):
        for t in st.session_state.audio_tasks: st.session_state[f"chk_{t['url']}"] = True
        st.rerun()
    if c_g2.button("🌐 全部取消"):
        for t in st.session_state.audio_tasks: st.session_state[f"chk_{t['url']}"] = False
        st.rerun()

    for folder in sorted(grouped.keys()):
        items = grouped[folder]
        with st.expander(f"📁 資料夾: {folder} ({len(items)} 個)", expanded=True):
            c1, c2, _ = st.columns([1, 1, 8])
            if c1.button(f"全選 {folder}", key=f"all_{folder}"):
                for item in items: st.session_state[f"chk_{item['url']}"] = True
                st.rerun()
            if c2.button(f"清空 {folder}", key=f"none_{folder}"):
                for item in items: st.session_state[f"chk_{item['url']}"] = False
                st.rerun()
            
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    st.session_state[f"chk_{item['url']}"] = st.checkbox(f"🎵 {item['file']}", key=f"chk_{item['url']}", value=st.session_state[f"chk_{item['url']}"])

    final_selection = [t for t in st.session_state.audio_tasks if st.session_state.get(f"chk_{t['url']}", False)]

    if st.button(f"🚀 2. 執行 AI 專業後製 ({len(final_selection)} 個)"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            st_text = st.empty()
            for i, task in enumerate(final_selection):
                st_text.text(f"正在進行專業後製: {task['file']}")
                try:
                    r = requests.get(task['url'], timeout=10)
                    if r.status_code == 200:
                        processed = process_audio_pro(r.content, task['file'])
                        master_zip.writestr(f"{task['folder']}/{task['file']}", processed)
                except: pass
                p_bar.progress((i + 1) / len(final_selection))
            st_text.text("✨ AI 處理與音量平衡完成！")
        
        st.download_button("⬇️ 下載專業版分類包", master_zip_io.getvalue(), f"{user_id}_Pro_Fixed.zip")
