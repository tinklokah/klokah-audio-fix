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

# 嘗試協助 pydub 尋找 ffmpeg
try:
    AudioSegment.converter = "ffmpeg"
except:
    pass

# --- 核心後製引擎 (保持你的規格要求) ---
def process_audio_pro_stable(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]
        audio = audio.compress_dynamic_range(threshold=-18.0, ratio=3.5, attack=5.0, release=50.0)
        audio = audio.normalize(headroom=6.0)
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 介面設定 ---
st.set_page_config(page_title="族語資料夾選取版", layout="wide")
st.title("🎙️ 族語全自動：資料夾選取 + 專業平穩後製")

# 初始化：這本筆記本用來記哪些「原始 ID 資料夾」被選中了
if 'selected_folders' not in st.session_state:
    st.session_state.selected_folders = set() # 用 set 避免重複
if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []

user_id = st.text_input("輸入帳號 ID", value="picex11301")

# --- 3. API 抓取邏輯 ---
if st.button("🔍 1. 抓取清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        tasks = []
        def scan_api(obj, p_name="未分類"):
            if isinstance(obj, dict):
                parent = obj.get('listTitle') or p_name
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        original_id = v.split('/')[-2] if len(v.split('/')) >= 2 else "others"
                        tasks.append({
                            "url": full_url, 
                            "parent": parent, 
                            "child": original_id, 
                            "file": os.path.basename(v)
                        })
                    else:
                        scan_api(v, parent)
            elif isinstance(obj, list):
                for i in obj: scan_api(i, p_name)
        scan_api(data)
        st.session_state.audio_tasks = tasks
        st.session_state.selected_folders = set() # 重新抓取時重置選取
        st.success(f"找到 {len(tasks)} 個音檔！")
    except:
        st.error("API 連線失敗")

# --- 4. 顯示區域：資料夾選取模式 ---
if st.session_state.audio_tasks:
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    
    st.write("---")
    st.info("💡 預設全不選，請點擊下方的【資料夾按鈕】來切換選取狀態。")
    
    # 建立一個全選所有資料夾的捷徑
    if st.button("🌐 選取/取消選取 所有大單元"):
        all_ids = {t['child'] for t in st.session_state.audio_tasks}
        if st.session_state.selected_folders == all_ids:
            st.session_state.selected_folders = set()
        else:
            st.session_state.selected_folders = all_ids
        st.rerun()

    for p_name in sorted(tree.keys()):
        st.subheader(f"📘 {p_name}")
        # 使用 columns 讓按鈕橫向排版
        cols = st.columns(4)
        for idx, c_id in enumerate(sorted(tree[p_name].keys())):
            file_count = len(tree[p_name][c_id])
            is_selected = c_id in st.session_state.selected_folders
            
            # 根據是否選取，顯示不同的圖示
            btn_label = f"✅ {c_id} ({file_count}檔)" if is_selected else f"📁 {c_id} ({file_count}檔)"
            
            with cols[idx % 4]:
                if st.button(btn_label, key=f"btn_{p_name}_{c_id}"):
                    if c_id in st.session_state.selected_folders:
                        st.session_state.selected_folders.remove(c_id)
                    else:
                        st.session_state.selected_folders.add(c_id)
                    st.rerun()

    # --- 5. 下載與執行 ---
    # 過濾出：如果音檔所屬的 child ID 在選取清單中，就納入處理
    final_selection = [t for t in st.session_state.audio_tasks if t['child'] in st.session_state.selected_folders]
    
    st.write("---")
    if st.button(f"🚀 2. 開始下載專業後製 (已選 {len(final_selection)} 個音檔)"):
        if not final_selection:
            st.warning("請先點擊資料夾按鈕選擇要下載的單元。")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                st_text = st.empty()
                for i, task in enumerate(final_selection):
                    st_text.text(f"正在後製: {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_pro_stable(r.content)
                            # 儲存結構：大單元標題 / 原始 ID / 檔名
                            master_zip_io_name = f"{task['parent']}/{task['child']}/{task['file']}"
                            master_zip.writestr(master_zip_io_name, processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection))
                st_text.text("✨ 處理與打包完成！")
            
            st.download_button(
                "⬇️ 下載已選單元後製包", 
                master_zip_io.getvalue(), 
                f"{user_id}_Selected_Pro.zip"
            )
