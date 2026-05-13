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

# --- 核心功能 1：去頭尾靜音與音質優化 ---
def process_audio_bytes(audio_bytes):
    try:
        # 讀取音檔
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 轉換為 wav 格式供 librosa 降噪處理
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        
        # 輕微降噪
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.7)
        
        # 轉回 pydub 進行去頭尾靜音
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)
        
        # 偵測非靜音區段 (去頭尾)
        # min_silence_len: 200ms 以上才算靜音 / silence_thresh: 低於 -48dB 算靜音
        intervals = detect_nonsilent(audio, min_silence_len=200, silence_thresh=-48)
        
        if intervals:
            start_trim = intervals[0][0]
            end_trim = intervals[-1][1]
            # 留一點緩衝 (前後各留 100ms)，避免聽起來太突兀
            audio = audio[max(0, start_trim-100) : min(len(audio), end_trim+100)]
        
        # 音量標準化與動態壓縮 (讓聲音聽起來飽滿)
        audio = audio.normalize(headroom=0.1)
        audio = audio.compress_dynamic_range(threshold=-12.0, ratio=4.0)
        
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except Exception as e:
        # 如果處理出錯，回傳原始檔案
        return audio_bytes

# --- 網頁介面 ---
st.set_page_config(page_title="族語全自動下載優化", page_icon="🎧", layout="wide")
st.title("🎧 族語全自動：帳號驅動下載器")

# 輸入帳號
user_id = st.text_input("請輸入帳號 ID", value="picex11301")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []

# --- 核心功能 2：自動分類資料夾 ---
if st.button("🔍 1. 抓取清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        
        if isinstance(data, dict) and data.get("message") == "帳號無效":
            st.error("伺服器回傳帳號無效，請確認帳號是否正確或需登入。")
        else:
            tasks = []
            # 遞迴掃描 JSON 並根據 title 分類資料夾
            def scan(obj, folder="未分類"):
                if isinstance(obj, dict):
                    # 只要抓到標題，就更新當前的資料夾名稱
                    current_folder = obj.get('title') or obj.get('name') or folder
                    for k, v in obj.items():
                        if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                            full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                            tasks.append({"url": full_url, "folder": current_folder, "file": os.path.basename(v)})
                        else:
                            scan(v, current_folder)
                elif isinstance(obj, list):
                    for i in obj: scan(i, folder)

            scan(data)
            st.session_state.audio_tasks = tasks
            st.success(f"找到 {len(tasks)} 個音檔！")
    except Exception as e:
        st.error(f"抓取失敗: {e}")

# --- 核心功能 3：選擇音檔功能 (按資料夾分組) ---
if st.session_state.audio_tasks:
    st.write("### 📂 勾選要下載的單元")
    
    # 將任務按資料夾分組顯示
    grouped = {}
    for t in st.session_state.audio_tasks:
        grouped.setdefault(t['folder'], []).append(t)
    
    final_selection = []
    
    # 建立多選介面
    for folder_name, items in grouped.items():
        with st.expander(f"📁 {folder_name} (共 {len(items)} 個檔案)", expanded=True):
            # 每行顯示 3 個 Checkbox
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    if st.checkbox(f"🎵 {item['file']}", key=f"sel_{item['url']}", value=True):
                        final_selection.append(item)

    st.write("---")
    
    if st.button(f"🚀 2. 開始下載並去頭尾靜音 ({len(final_selection)} 個)"):
        master_zip_io = io.BytesIO()
        with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
            p_bar = st.progress(0)
            status = st.empty()
            
            for i, task in enumerate(final_selection):
                status.text(f"正在處理 ({i+1}/{len(final_selection)}): {task['file']}")
                try:
                    r = requests.get(task['url'], timeout=10)
                    if r.status_code == 200:
                        # 執行去頭尾靜音與優化
                        processed_audio = process_audio_bytes(r.content)
                        # 存入 ZIP，自動按資料夾分類
                        master_zip.writestr(f"{task['folder']}/{task['file']}", processed_audio)
                except:
                    st.warning(f"跳過失敗檔案: {task['file']}")
                p_bar.progress((i + 1) / len(final_selection))
            
            status.text("✅ 所有檔案處理完成！")
        
        st.download_button(
            label="⬇️ 下載最終分類優化包",
            data=master_zip_io.getvalue(),
            file_name=f"{user_id}_Audio_Fixed.zip",
            mime="application/zip"
        )
