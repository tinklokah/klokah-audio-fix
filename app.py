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

# --- 1. 核心後製：讓幅度一致的祕密 ---
def process_audio_balanced(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # A. AI 降噪
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

        # C. 【關鍵】動態範圍壓縮：這會讓幅度變得很一致
        # 它會把大聲的部分壓低，並在後段自動補償小聲的部分
        audio = audio.compress_dynamic_range(
            threshold=-20.0, # 低於此分貝的聲音會被拉近
            ratio=4.0,       # 壓縮力道：數值越高，整段聲音越平整
            attack=5.0,
            release=50.0
        )

        # D. 最後峰值鎖定 (-6dB)
        audio = audio.normalize(headroom=6.0)
        
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 2. 介面設定 ---
st.set_page_config(page_title="族語全抓取專業版", layout="wide")
st.title("🎙️ 族語全自動：修正「南島的故事」與音量平整化")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []
if 'selected_folders' not in st.session_state:
    st.session_state.selected_folders = set()

user_id = st.text_input("輸入帳號 ID", value="picex11301")

# --- 3. 強化版 API 掃描 (確保抓到所有 listTitle) ---
if st.button("🔍 1. 抓取所有單元"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        tasks = []
        
        def scan_full(obj, current_title="未分類"):
            if isinstance(obj, dict):
                # 更新標題：這行是抓到「南島的故事」的關鍵
                new_title = obj.get('listTitle') or obj.get('title') or current_title
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        path_parts = v.split('/')
                        original_id = path_parts[-2] if len(path_parts) >= 2 else "others"
                        tasks.append({
                            "url": full_url, "parent": new_title, "child": original_id, "file": os.path.basename(v)
                        })
                    elif isinstance(v, (dict, list)):
                        scan_full(v, new_title)
            elif isinstance(obj, list):
                for item in obj: scan_full(item, current_title)

        scan_full(data)
        st.session_state.audio_tasks = tasks
        st.session_state.selected_folders = set() 
        st.success(f"抓取成功！共找到 {len(tasks)} 個音檔。")
    except:
        st.error("API 解析失敗。")

# --- 4. 資料夾選取區域 (穩定無報錯版) ---
if st.session_state.audio_tasks:
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    
    st.write("---")
    st.info("💡 預設不選。點擊資料夾按鈕選取（✅ 為選中）。")

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

    # --- 5. 打包下載 ---
    final_sel = [t for t in st.session_state.audio_tasks if t['child'] in st.session_state.selected_folders]
    
    if st.button(f"🚀 2. 開始下載專業後製 ({len(final_sel)} 檔)"):
        if not final_sel:
            st.warning("請先選取單元。")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                for i, task in enumerate(final_sel):
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_balanced(r.content)
                            # 結構：大標題 / 原始 ID / 檔名
                            master_zip.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_sel))
            
            st.download_button("⬇️ 下載專業平衡包", master_zip_io.getvalue(), f"{user_id}_Balanced.zip")
