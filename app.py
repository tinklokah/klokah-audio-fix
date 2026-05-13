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

# 協助 pydub 尋找 ffmpeg
try:
    AudioSegment.converter = "ffmpeg"
except:
    pass

# --- 1. 專業後製引擎：降噪 + 平穩化 + 去頭尾 ---
def process_audio_pro_stable(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # A. AI 降噪 (0.75)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # B. 去頭尾靜音 (保留 0.2s)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]

        # C. 解決忽大忽小：動態範圍壓縮 (解決錄音起伏)
        audio = audio.compress_dynamic_range(threshold=-18.0, ratio=3.5, attack=5.0, release=50.0)

        # D. 最後峰值鎖定：-6dB
        audio = audio.normalize(headroom=6.0)
        
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 2. 介面設定 ---
st.set_page_config(page_title="族語全抓取版", layout="wide")
st.title("🎙️ 族語全自動：全單元掃描 + 資料夾選取")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []
if 'selected_folders' not in st.session_state:
    st.session_state.selected_folders = set()

user_id = st.text_input("輸入帳號 ID", value="picex11301")

# --- 3. 修正後的 API 遍歷邏輯 (確保抓到南島的故事) ---
if st.button("🔍 1. 抓取所有單元清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        tasks = []
        
        def scan_full(obj, last_title="未分類"):
            if isinstance(obj, dict):
                # 更新目前的標題 (這會抓到 04-南島的故事)
                current_title = obj.get('listTitle') or obj.get('title') or last_title
                
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        # 抓取原始路徑 ID
                        path_parts = v.split('/')
                        original_id = path_parts[-2] if len(path_parts) >= 2 else "others"
                        
                        tasks.append({
                            "url": full_url, 
                            "parent": current_title, 
                            "child": original_id, 
                            "file": os.path.basename(v)
                        })
                    elif isinstance(v, (dict, list)):
                        scan_full(v, current_title)
            elif isinstance(obj, list):
                for item in obj:
                    scan_full(item, last_title)

        scan_full(data)
        st.session_state.audio_tasks = tasks
        st.session_state.selected_folders = set() # 重新抓取則清空選取
        st.success(f"抓取成功！共找到 {len(tasks)} 個音檔。")
    except:
        st.error("API 解析失敗，請確認 ID 是否正確。")

# --- 4. 顯示與選取 (按資料夾選取) ---
if st.session_state.audio_tasks:
    # 建立分類結構
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    
    st.write("---")
    st.info("💡 預設全不選。請點擊下方的【資料夾按鈕】來選取要後製的單元。")

    for p_name in sorted(tree.keys()):
        st.subheader(f"📘 {p_name}")
        cols = st.columns(4)
        for idx, c_id in enumerate(sorted(tree[p_name].keys())):
            items = tree[p_name][c_id]
            is_selected = c_id in st.session_state.selected_folders
            
            # 按鈕標籤與顏色模擬
            btn_label = f"✅ {c_id} ({len(items)}檔)" if is_selected else f"📁 {c_id} ({len(items)}檔)"
            
            with cols[idx % 4]:
                if st.button(btn_label, key=f"btn_{p_name}_{c_id}"):
                    if is_selected:
                        st.session_state.selected_folders.remove(c_id)
                    else:
                        st.session_state.selected_folders.add(c_id)
                    st.rerun()

    # --- 5. 下載執行 ---
    final_selection = [t for t in st.session_state.audio_tasks if t['child'] in st.session_state.selected_folders]
    
    st.write("---")
    if st.button(f"🚀 2. 開始下載專業後製 (已選 {len(final_selection)} 檔)"):
        if not final_selection:
            st.warning("請先選取上方單元。")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                st_msg = st.empty()
                for i, task in enumerate(final_selection):
                    st_msg.text(f"正在處理: {task['parent']} / {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_pro_stable(r.content)
                            # 儲存：大單元 / 原始 ID / 檔名
                            master_zip.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection))
                st_msg.text("✨ 處理完成！")
            
            st.download_button(
                "⬇️ 下載已選單元包", 
                master_zip_io.getvalue(), 
                f"{user_id}_Audio_Fixed.zip"
            )
