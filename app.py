import streamlit as st
import requests
import io
import os
import zipfile
import noisereduce as nr
import librosa
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

# --- 核心優化：去頭尾靜音 + 深度音平衡 ---
def process_audio_bytes(audio_bytes, target_dBFS=-20.0):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 1. 轉換格式與降噪 (librosa)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.6) # 降噪
        
        # 2. 轉回 pydub 進行空間處理
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)
        
        # 3. 去頭尾靜音
        intervals = detect_nonsilent(audio, min_silence_len=200, silence_thresh=-48)
        if intervals:
            audio = audio[max(0, intervals[0][0]-100) : min(len(audio), intervals[-1][1]+100)]
        
        # 4. 【核心更新】深度音平衡 (Loudness Matching)
        # 計算當前音量與目標音量的差距
        change_in_dBFS = target_dBFS - audio.dBFS
        audio = audio.apply_gain(change_in_dBFS)
        
        # 5. 防止爆音 (Limiter)
        # 如果平衡後最高峰值超過 -1dB，則進行壓縮以防止破音
        if audio.max_dBFS > -1.0:
            audio = audio.normalize(headroom=1.0)
            
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 網頁介面 ---
st.set_page_config(page_title="族語全自動優化版", page_icon="⚖️", layout="wide")
st.title("⚖️ 族語全自動：去靜音 + 深度音量平衡")

# 初始化 Session State
if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []

user_id = st.text_input("請輸入帳號 ID", value="picex11301")

if st.button("🔍 1. 抓取清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        tasks = []
        def scan_by_url(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        path_parts = v.split('/')
                        folder_name = path_parts[-2] if len(path_parts) >= 2 else "其他"
                        tasks.append({"url": full_url, "folder": folder_name, "file": os.path.basename(v)})
                        if f"chk_{full_url}" not in st.session_state:
                            st.session_state[f"chk_{full_url}"] = True
                    else:
                        scan_by_url(v)
            elif isinstance(obj, list):
                for item in obj: scan_by_url(item)
        scan_by_url(data)
        st.session_state.audio_tasks = tasks
        st.success(f"找到 {len(tasks)} 個音檔！")
    except Exception as e:
        st.error(f"抓取失敗: {e}")

# --- 選擇區域 ---
if st.session_state.audio_tasks:
    grouped = {}
    for t in st.session_state.audio_tasks:
        grouped.setdefault(t['folder'], []).append(t)
    
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
        with st.expander(f"📁 資料夾 ID: {folder} (共 {len(items)} 個)", expanded=True):
            c1, c2, _ = st.columns([1, 1, 8])
            if c1.button(f"全選 {folder}", key=f"all_{folder}"):
                for item in items: st.session_state[f"chk_{item['url']}"] = True
                st.rerun()
            if c2.button(f"清空 {folder}", key=f"none_{folder}"):
                for item in items: st.session_state[f"chk_{item['url']}"] = False
                st.rerun()
            
            st.write("---")
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    st.checkbox(f"🎵 {item['file']}", key=f"chk_{item['url']}")

    final_selection = [t for t in st.session_state.audio_tasks if st.session_state.get(f"chk_{t['url']}", False)]

    st.write("---")
    # 增加音量平衡強度調整 (選配)
    target_vol = st.slider("目標音量強度 (dBFS)", -30.0, -10.0, -20.0, help="數字越大聲音越響亮，預設 -20 是舒適標準。")

    if st.button(f"🚀 2. 開始平衡下載 ({len(final_selection)} 個)"):
        if not final_selection:
            st.warning("請先勾選音檔。")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                status = st.empty()
                for i, task in enumerate(final_selection):
                    status.text(f"音量平衡處理中: {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            # 帶入目標音量進行平衡
                            processed = process_audio_bytes(r.content, target_dBFS=target_vol)
                            master_zip.writestr(f"{task['folder']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection))
                status.text("✅ 音平衡處理完成！")
            
            st.download_button("⬇️ 下載最終平衡包", master_zip_io.getvalue(), f"{user_id}_Balanced.zip")
