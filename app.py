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

# --- 核心引擎：極致純淨 (強力降噪 + 噪音門) ---
def process_audio_super_clean(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 1. 強力 AI 降噪 (提高到 0.85，專門對付沙沙聲)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.85)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # 2. 【新增】噪音門邏輯 (Noise Gate)
        # 如果一段聲音太小 (低於 -42dB)，直接判定為噪音並靜音
        def noise_gate(seg, threshold=-42.0):
            return seg.compress_dynamic_range(threshold=threshold, ratio=20.0) if seg.dBFS < threshold else seg
        
        # 3. 去頭尾靜音
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]

        # 4. 溫和壓縮 (Ratio 3.5)
        # 讓波形還是有一點起伏，但整體響度足夠，聽起來最舒服
        audio = audio.compress_dynamic_range(
            threshold=-26.0, 
            ratio=3.5,      
            attack=5.0, 
            release=150.0   
        )

        # 5. 適度增益 (+8dB)
        # 不再暴力拉大，確保底噪不回潮
        audio = audio + 8 

        # 6. 標準化至 -6dB
        audio = audio.normalize(headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except Exception as e:
        return audio_bytes

# --- Streamlit 介面邏輯 (維持分類架構) ---
st.set_page_config(page_title="族語極致純淨版", layout="wide")
st.title("🎙️ 族語全自動：極致純淨版 (強力降噪 + 噪音門)")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []
if 'selected_folders' not in st.session_state:
    st.session_state.selected_folders = set()

user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 1. 抓取雲端音檔清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json()
        tasks = []
        def scan(obj, title="未分類"):
            if isinstance(obj, dict):
                cur = obj.get('listTitle') or obj.get('title') or title
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        oid = v.split('/')[-2] if len(v.split('/')) >= 2 else "others"
                        tasks.append({"url": v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}", 
                                      "parent": cur, "child": oid, "file": os.path.basename(v)})
                    elif isinstance(v, (dict, list)): scan(v, cur)
            elif isinstance(obj, list):
                for i in obj: scan(i, title)
        scan(data)
        st.session_state.audio_tasks = tasks
        st.session_state.selected_folders = set()
        st.success(f"找到 {len(tasks)} 個音檔。")
    except: st.error("API 連線失敗")

if st.session_state.audio_tasks:
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    st.write("---")
    for p_name in sorted(tree.keys()):
        st.subheader(f"📘 {p_name}")
        cols = st.columns(4)
        for idx, c_id in enumerate(sorted(tree[p_name].keys())):
            items = tree[p_name][c_id]
            is_sel = c_id in st.session_state.selected_folders
            btn = f"✅ {c_id} ({len(items)}檔)" if is_sel else f"📁 {c_id} ({len(items)}檔)"
            with cols[idx % 4]:
                if st.button(btn, key=f"btn_{p_name}_{c_id}"):
                    if is_sel: st.session_state.selected_folders.remove(c_id)
                    else: st.session_state.selected_folders.add(c_id)
                    st.rerun()

    final = [t for t in st.session_state.audio_tasks if t['child'] in st.session_state.selected_folders]
    st.write("---")
    if st.button(f"🚀 2. 執行極致純淨處理 ({len(final)} 檔)"):
        if not final: st.warning("請選取資料夾。")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as mz:
                p_bar = st.progress(0)
                for i, task in enumerate(final):
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_super_clean(r.content)
                            mz.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final))
            st.download_button("⬇️ 下載極致純淨包", zip_io.getvalue(), f"{user_id}_Super_Clean.zip")
