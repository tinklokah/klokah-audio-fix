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

# --- 1. 暴力平穩引擎：把波形壓平 ---
def process_audio_brickwall(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # A. 降噪
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.8)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # B. 【核心】強力動態壓縮器 (讓幅度一致)
        # Threshold 設更低，Ratio 設更高，強行把大聲拉低，小聲拉高
        audio = audio.compress_dynamic_range(
            threshold=-24.0, # 更敏感的門檻
            ratio=6.0,       # 更強大的壓縮比 (原本是 3~4)
            attack=5.0,
            release=100.0    # 讓聲音平穩恢復
        )

        # C. 峰值標準化
        audio = audio.normalize(headroom=3.0) # 讓音量更大一點
        
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 2. 介面設定 ---
st.set_page_config(page_title="族語波形平整版", layout="wide")
st.title("🎙️ 族語全自動：波形極致平整化處理")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []
if 'selected_folders' not in st.session_state:
    st.session_state.selected_folders = set()

user_id = st.text_input("輸入帳號 ID", value="picex11301")

# --- 3. 抓取清單 ---
if st.button("🔍 1. 抓取有音檔的單元"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url)
        data = res.json()
        tasks = []
        def scan(obj, title="未分類"):
            if isinstance(obj, dict):
                new_title = obj.get('listTitle') or obj.get('title') or title
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        path_parts = v.split('/')
                        oid = path_parts[-2] if len(path_parts) >= 2 else "others"
                        tasks.append({
                            "url": v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}",
                            "parent": new_title, "child": oid, "file": os.path.basename(v)
                        })
                    elif isinstance(v, (dict, list)): scan(v, new_title)
            elif isinstance(obj, list):
                for i in obj: scan(i, title)
        scan(data)
        st.session_state.audio_tasks = tasks
        st.session_state.selected_folders = set()
        st.success(f"找到 {len(tasks)} 個有效音檔！")
    except: st.error("API 連線失敗")

# --- 4. 分類按鈕 (無勾選衝突版) ---
if st.session_state.audio_tasks:
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    
    st.write("---")
    st.info("請點擊下方資料夾按鈕來選取。")

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

    # --- 5. 後製打包 ---
    final = [t for t in st.session_state.audio_tasks if t['child'] in st.session_state.selected_folders]
    if st.button(f"🚀 2. 執行波形平整後製 ({len(final)} 檔)"):
        if not final: st.warning("請先選取單元。")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as mz:
                bar = st.progress(0)
                for i, task in enumerate(final):
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_brickwall(r.content)
                            mz.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    bar.progress((i + 1) / len(final))
            st.download_button("⬇️ 下載平整版音檔包", zip_io.getvalue(), f"{user_id}_Brickwall.zip")
