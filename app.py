import streamlit as st
import requests
import io
import os
import zipfile
import librosa
import soundfile as sf
import noisereduce as nr
from pydub import AudioSegment, effects
from pydub.silence import detect_nonsilent

# --- 核心優化：純 Python 專業級音平衡 ---
def process_audio_pure_python(audio_bytes, target_dBFS=-18.0):
    try:
        # 1. 讀入音檔並初步降噪
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 轉 wav 供 librosa 降噪 (降噪參數移植 0.75)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        # 轉回 pydub
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # 2. 去頭尾靜音 (參數移植：前後保留 200ms)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            start_trim = max(0, intervals[0][0] - 200)
            end_trim = min(len(audio), intervals[-1][1] + 200)
            audio = audio[start_trim:end_trim]

        # 3. 【關鍵】模擬 Loudnorm 的音平衡
        # A. RMS 響度匹配：將「平均體感音量」對齊到 -18 dBFS
        change_in_dBFS = target_dBFS - audio.dBFS
        audio = audio.apply_gain(change_in_dBFS)
        
        # B. 動態壓縮 (Compressor)：這是讓聲音變「厚實」的關鍵
        # 壓縮太大的波峰，讓小聲的細節浮現
        audio = audio.compress_dynamic_range(
            threshold=-16.0, # 低於 -16dB 的聲音會被壓縮
            ratio=3.0,       # 壓縮比
            attack=5.0,      # 反應速度 (ms)
            release=50.0     # 釋放速度 (ms)
        )

        # 4. 【強制峰值】推至 -6dB 
        # 使用 pydub 的 normalize 並設定 headroom 為 6.0，確保最高點就在 -6dB
        audio = effects.normalize(audio, headroom=6.0)

        # 5. 輸出
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except Exception as e:
        return audio_bytes

# --- 網頁介面 (與之前相同) ---
st.set_page_config(page_title="族語 AI 優化 (免FFmpeg版)", page_icon="⚖️", layout="wide")
st.title("⚖️ 族語全自動：純 Python 專業音平衡版")

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
        st.success(f"找到 {len(tasks)} 個音檔。")
    except: st.error("API 連線失敗")

if st.session_state.audio_tasks:
    grouped = {}
    for t in st.session_state.audio_tasks: grouped.setdefault(t['folder'], []).append(t)
    
    st.write("---")
    # 全域控制
    col_g1, col_g2, _ = st.columns([1, 1, 8])
    if col_g1.button("🌐 全部全選"):
        for t in st.session_state.audio_tasks: st.session_state[f"chk_{t['url']}"] = True
        st.rerun()
    if col_g2.button("🌐 全部取消"):
        for t in st.session_state.audio_tasks: st.session_state[f"chk_{t['url']}"] = False
        st.rerun()

    for folder in sorted(grouped.keys()):
        items = grouped[folder]
        with st.expander(f"📁 資料夾: {folder} ({len(items)})", expanded=True):
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

    if st.button(f"🚀 2. 執行深度平衡處理 ({len(final_selection)} 個)"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            st_text = st.empty()
            for i, task in enumerate(final_selection):
                st_text.text(f"處理中: {task['file']}")
                try:
                    r = requests.get(task['url'], timeout=10)
                    if r.status_code == 200:
                        # 執行純 Python 專業處理
                        processed = process_audio_pure_python(r.content)
                        master_zip.writestr(f"{task['folder']}/{task['file']}", processed)
                except: pass
                p_bar.progress((i + 1) / len(final_selection))
            st_text.text("✨ 處理完成！")
        
        st.download_button("⬇️ 下載深度平衡分類包", master_zip_io.getvalue(), f"{user_id}_DeepBalanced.zip")
