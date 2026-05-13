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

# --- 1. 專業音訊引擎 (移植自 v3.6 核心) ---
def process_audio_pro(audio_bytes, filename):
    try:
        # 讀入音訊
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # A. AI 降噪 (比照原程式參數 0.75)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # B. 去頭尾靜音 (前後保留 200ms)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            start_trim = max(0, intervals[0][0] - 200)
            end_trim = min(len(audio), intervals[-1][1] + 200)
            audio = audio[start_trim:end_trim]

        # C. 響度平衡與厚度 (-18 dBFS)
        diff = -18.0 - audio.dBFS
        audio = audio.apply_gain(diff)
        audio = audio.compress_dynamic_range(threshold=-16.0, ratio=3.0, attack=5.0, release=50.0)

        # D. 強制峰值鎖定 -6dB (headroom=6.0)
        audio = effects.normalize(audio, headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except Exception as e:
        return audio_bytes

# --- 2. 介面與狀態管理 ---
st.set_page_config(page_title="族語教材終極版", layout="wide")
st.title("🎙️ 族語全自動：專業後製與原始路徑分類工具")

if 'tasks' not in st.session_state:
    st.session_state.tasks = []

user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 1. 抓取教材層級"):
    try:
        res = requests.get(f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}", timeout=15)
        data = res.json()
        tasks = []
        def scan(obj, p_folder="未分類"):
            if isinstance(obj, dict):
                parent = obj.get('listTitle') or p_folder
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        parts = v.split('/')
                        original_id = parts[-2] if len(parts) >= 2 else "others"
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        filename = os.path.basename(v)
                        
                        tasks.append({
                            "url": full_url, "parent": parent, "child": original_id, "file": filename
                        })
                        if f"chk_{full_url}" not in st.session_state:
                            st.session_state[f"chk_{full_url}"] = True
                    else: scan(v, parent)
            elif isinstance(obj, list):
                for i in obj: scan(i, p_folder)
        scan(data)
        st.session_state.tasks = tasks
        st.success(f"找到 {len(tasks)} 個檔案。")
    except: st.error("抓取失敗")

# --- 3. 顯示與穩定勾選 ---
if st.session_state.tasks:
    tree = {}
    for t in st.session_state.tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)

    st.write("---")
    c_g1, c_g2, _ = st.columns([1, 1, 8])
    if c_g1.button("🌐 全部全選"):
        for t in st.session_state.tasks: st.session_state[f"chk_{t['url']}"] = True
        st.rerun()
    if c_g2.button("🌐 全部取消"):
        for t in st.session_state.tasks: st.session_state[f"chk_{t['url']}"] = False
        st.rerun()

    for p_name in sorted(tree.keys()):
        st.header(f"📘 {p_name}")
        child_dict = tree[p_name]
        for c_id in sorted(child_dict.keys()):
            items = child_dict[c_id]
            with st.expander(f"📁 原始路徑 ID: {c_id} ({len(items)} 檔)", expanded=True):
                ca, cn, _ = st.columns([1, 1, 8])
                if ca.button(f"全選 {c_id}", key=f"all_{p_name}_{c_id}"):
                    for i in items: st.session_state[f"chk_{i['url']}"] = True
                    st.rerun()
                if cn.button(f"清空 {c_id}", key=f"none_{p_name}_{c_id}"):
                    for i in items: st.session_state[f"chk_{i['url']}"] = False
                    st.rerun()
                
                cols = st.columns(3)
                for idx, item in enumerate(items):
                    with cols[idx % 3]:
                        st.session_state[f"chk_{item['url']}"] = st.checkbox(
                            f"🎵 {item['file']}", 
                            key=f"chk_{item['url']}", 
                            value=st.session_state.get(f"chk_{item['url']}", True)
                        )

    # --- 4. 後製處理與打包 ---
    final_selection = [t for t in st.session_state.tasks if st.session_state.get(f"chk_{t['url']}", False)]
    st.write("---")
    if st.button(f"🚀 2. 執行 AI 專業後製並打包 ({len(final_selection)} 個)"):
        if not final_selection:
            st.warning("請先勾選檔案")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                st_text = st.empty()
                for i, task in enumerate(final_selection):
                    st_text.text(f"處理中: {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_pro(r.content, task['file'])
                            # 按照層級存檔
                            master_zip.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection))
                st_text.text("✨ AI 後製與分類打包完成！")
            st.download_button("⬇️ 下載專業分類包", zip_io.getvalue(), f"{user_id}_Final_Pro.zip")
