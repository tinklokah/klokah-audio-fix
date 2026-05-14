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

# --- 1. 核心引擎：音量暴力平衡 + 硬限制 ---
def process_audio_brickwall(audio_bytes):
    try:
        # 讀取音訊
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # A. AI 降噪 (預防放大音量時底噪太重)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # B. 去頭尾靜音 (保留 0.2s 緩衝)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]

        # C. 動態壓縮：先把高低差距縮小
        audio = audio.compress_dynamic_range(
            threshold=-24.0, 
            ratio=6.0, 
            attack=5.0, 
            release=100.0
        )

        # D. 【關鍵】暴力增益：讓波形往兩邊撐開
        audio = audio + 15 

        # E. 【關鍵】硬限制：所有波峰統一在 -6dB 削平
        # 使用 headroom=6.0 確保最高點死死鎖在 -6dB
        audio = audio.normalize(headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except Exception as e:
        return audio_bytes

# --- 2. Streamlit 介面設定 ---
st.set_page_config(page_title="族語音量平衡專家", layout="wide")
st.title("🎙️ 族語全自動：音量暴力平衡 & 分類打包")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []
if 'selected_folders' not in st.session_state:
    st.session_state.selected_folders = set()

user_id = st.text_input("輸入帳號 ID", value="picex11301")

# --- 3. API 抓取邏輯 (全域掃描) ---
if st.button("🔍 1. 抓取雲端音檔清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        tasks = []
        
        def deep_scan(obj, last_title="未分類"):
            if isinstance(obj, dict):
                current_title = obj.get('listTitle') or obj.get('title') or last_title
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        path_parts = v.split('/')
                        oid = path_parts[-2] if len(path_parts) >= 2 else "others"
                        tasks.append({
                            "url": full_url, 
                            "parent": current_title, 
                            "child": oid, 
                            "file": os.path.basename(v)
                        })
                    elif isinstance(v, (dict, list)):
                        deep_scan(v, current_title)
            elif isinstance(obj, list):
                for i in obj: deep_scan(i, last_title)

        deep_scan(data)
        st.session_state.audio_tasks = tasks
        st.session_state.selected_folders = set()
        st.success(f"掃描完成！共找到 {len(tasks)} 個音檔連結。")
    except:
        st.error("API 連線失敗，請檢查網路或 ID。")

# --- 4. 顯示與選取區域 ---
if st.session_state.audio_tasks:
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    
    st.write("---")
    st.info("💡 點擊下方資料夾按鈕選取。選中的資料夾會顯示 ✅。")

    for p_name in sorted(tree.keys()):
        st.subheader(f"📘 {p_name}")
        cols = st.columns(4)
        for idx, c_id in enumerate(sorted(tree[p_name].keys())):
            items = tree[p_name][c_id]
            is_sel = c_id in st.session_state.selected_folders
            btn_label = f"✅ {c_id} ({len(items)}檔)" if is_sel else f"📁 {c_id} ({len(items)}檔)"
            
            with cols[idx % 4]:
                if st.button(btn_label, key=f"btn_{p_name}_{c_id}"):
                    if is_sel: st.session_state.selected_folders.remove(c_id)
                    else: st.session_state.selected_folders.add(c_id)
                    st.rerun()

    # --- 5. 下載與後製 ---
    final_selection = [t for t in st.session_state.audio_tasks if t['child'] in st.session_state.selected_folders]
    
    st.write("---")
    if st.button(f"🚀 2. 開始執行暴力平衡打包 ({len(final_selection)} 檔)"):
        if not final_selection:
            st.warning("請先選取要處理的資料夾。")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as mz:
                p_bar = st.progress(0)
                st_msg = st.empty()
                for i, task in enumerate(final_selection):
                    st_msg.text(f"正在後製 (音量暴力平衡中): {task['parent']} - {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_brickwall(r.content)
                            # 建立層級：大單元標題 / 原始 ID / 檔名
                            mz.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection))
                st_msg.text("✨ 所有音檔已壓平成磚牆，處理完成！")
            
            st.download_button(
                "⬇️ 下載暴力平衡音檔包", 
                zip_io.getvalue(), 
                f"{user_id}_Brickwall_Balanced.zip"
            )
