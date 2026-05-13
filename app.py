import streamlit as st
import requests
import io
import os
import zipfile
import re
import noisereduce as nr
import librosa
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

# --- 核心優化：去頭尾靜音 (不變) ---
def process_audio_bytes(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.7)
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)
        
        # 去頭尾靜音
        intervals = detect_nonsilent(audio, min_silence_len=200, silence_thresh=-48)
        if intervals:
            audio = audio[max(0, intervals[0][0]-100) : min(len(audio), intervals[-1][1]+100)]
        
        audio = audio.normalize(headroom=0.1)
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 網頁介面 ---
st.set_page_config(page_title="族語 ID 自動分類版", page_icon="🗂️", layout="wide")
st.title("🗂️ 族語全自動：ID 資料夾精準分類器")

user_id = st.text_input("請輸入帳號 ID", value="picex11301")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []

if st.button("🔍 1. 抓取清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        
        tasks = []
        # 遍歷 JSON 尋找音檔網址
        def scan_by_url(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        # 補全網址
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        
                        # --- 核心邏輯：從網址提取資料夾 ID ---
                        # 範例：.../sound/70284/975783.mp3 -> 提取 70284
                        path_parts = v.split('/')
                        if len(path_parts) >= 2:
                            # 拿檔名前面那一個資料夾名
                            folder_name = path_parts[-2] 
                        else:
                            folder_name = "其他"
                            
                        tasks.append({
                            "url": full_url, 
                            "folder": folder_name, 
                            "file": os.path.basename(v)
                        })
                    else:
                        scan_by_url(v)
            elif isinstance(obj, list):
                for item in obj:
                    scan_by_url(item)

        scan_by_url(data)
        st.session_state.audio_tasks = tasks
        
        if tasks:
            st.success(f"找到 {len(tasks)} 個音檔！已根據網址結構完成 ID 分類。")
        else:
            st.warning("未找到音檔網址。")
    except Exception as e:
        st.error(f"抓取失敗: {e}")

# --- 選擇與下載 ---
if st.session_state.audio_tasks:
    # 建立分組
    grouped = {}
    for t in st.session_state.audio_tasks:
        grouped.setdefault(t['folder'], []).append(t)
    
    st.write("### 📂 確認下載分組 (以 ID 分類)")
    final_selection = []
    
    # 依照 ID 排序資料夾
    sorted_folders = sorted(grouped.keys())
    
    for folder in sorted_folders:
        items = grouped[folder]
        with st.expander(f"📁 資料夾 ID: {folder} (共 {len(items)} 個檔案)", expanded=True):
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    if st.checkbox(f"🎵 {item['file']}", key=f"sel_{item['url']}", value=True):
                        final_selection.append(item)

    if st.button(f"🚀 2. 批次處理並按 ID 打包 ({len(final_selection)} 個)"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            status = st.empty()
            for i, task in enumerate(final_selection):
                status.text(f"正在後製: {task['folder']}/{task['file']}")
                try:
                    r = requests.get(task['url'], timeout=10)
                    if r.status_code == 200:
                        processed = process_audio_bytes(r.content)
                        # 依照 ID 資料夾存入 ZIP
                        master_zip.writestr(f"{task['folder']}/{task['file']}", processed)
                except: pass
                p_bar.progress((i + 1) / len(final_selection))
            status.text("✅ 處理完成！")
        
        st.download_button("⬇️ 下載 ID 分類優化包", master_zip_io.getvalue(), f"{user_id}_ID_Grouped.zip")
