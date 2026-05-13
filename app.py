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

# --- 專業音訊處理引擎 (純 Python 模擬音量厚度) ---
def process_audio_final(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 1. 降噪處理 (參數 0.75)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # 2. 去頭尾靜音 (前後保留 200ms)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            start_trim = max(0, intervals[0][0] - 200)
            end_trim = min(len(audio), intervals[-1][1] + 200)
            audio = audio[start_trim:end_trim]

        # 3. 響度平衡與厚度感 (RMS Normalization)
        # 目標 -18 dBFS 平均響度
        diff = -18.0 - audio.dBFS
        audio = audio.apply_gain(diff)
        
        # 4. 動態壓縮 (讓聲音紮實，不刺耳)
        audio = audio.compress_dynamic_range(threshold=-16.0, ratio=3.0, attack=5.0, release=50.0)

        # 5. 強制峰值鎖定在 -6dB
        audio = effects.normalize(audio, headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 網頁 UI 邏輯 ---
st.set_page_config(page_title="族語專業後製工具", page_icon="🎙️", layout="wide")
st.title("🎙️ 族語全自動：專業後製與精準分類 (修正版)")

# 初始化存儲空間
if 'tasks' not in st.session_state:
    st.session_state.tasks = []
if 'sel_map' not in st.session_state:
    st.session_state.sel_map = {}

user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 1. 抓取 API 清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        new_tasks = []
        def scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        folder = v.split('/')[-2] if len(v.split('/')) >= 2 else "其他"
                        tid = f"{folder}_{os.path.basename(v)}"
                        new_tasks.append({"url": full_url, "folder": folder, "file": os.path.basename(v), "id": tid})
                        # 預設全部勾選
                        st.session_state.sel_map[tid] = True
                    else: scan(v)
            elif isinstance(obj, list):
                for i in obj: scan(i)
        scan(data)
        st.session_state.tasks = new_tasks
        st.success(f"找到 {len(new_tasks)} 個音檔！")
    except:
        st.error("連線 API 失敗，請檢查 ID 是否正確。")

# --- 列表與勾選 ---
if st.session_state.tasks:
    grouped = {}
    for t in st.session_state.tasks:
        grouped.setdefault(t['folder'], []).append(t)

    st.write("---")
    # 全域按鈕
    ga, gn, _ = st.columns([1, 1, 8])
    if ga.button("🌐 全部勾選"):
        for t in st.session_state.tasks: st.session_state.sel_map[t['id']] = True
        st.rerun()
    if gn.button("🌐 全部取消"):
        for t in st.session_state.tasks: st.session_state.sel_map[t['id']] = False
        st.rerun()

    for folder in sorted(grouped.keys()):
        items = grouped[folder]
        with st.expander(f"📁 資料夾 ID: {folder} ({len(items)} 個)", expanded=True):
            # 資料夾全選控制
            c1, c2, _ = st.columns([1, 1, 8])
            if c1.button(f"勾選此單元", key=f"all_{folder}"):
                for item in items: st.session_state.sel_map[item['id']] = True
                st.rerun()
            if c2.button(f"清空此單元", key=f"none_{folder}"):
                for item in items: st.session_state.sel_map[item['id']] = False
                st.rerun()
            
            # 顯示檔案
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    # 這裡不使用 key 直接綁定，而是用手動控制
                    is_checked = st.checkbox(item['file'], value=st.session_state.sel_map.get(item['id'], True), key=f"check_{item['id']}")
                    st.session_state.sel_map[item['id']] = is_checked

    # 執行處理
    final_list = [t for t in st.session_state.tasks if st.session_state.sel_map.get(t['id'])]

    st.write("---")
    if st.button(f"🚀 2. 開始後製打包 ({len(final_list)} 個)"):
        if not final_list:
            st.warning("請先勾選檔案")
        else:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                prog = st.progress(0)
                status = st.empty()
                for i, task in enumerate(final_list):
                    status.text(f"正在後製 (-6dB 峰值): {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_final(r.content)
                            zip_file.writestr(f"{task['folder']}/{task['file']}", processed)
                    except: pass
                    prog.progress((i + 1) / len(final_list))
                status.text("✨ 處理完成！")
            
            st.download_button("⬇️ 下載專業平衡包", zip_buffer.getvalue(), f"{user_id}_Pro_Balanced.zip")
