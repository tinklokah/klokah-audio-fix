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

# --- 核心引擎：純淨平衡 (減少沙沙聲，維持適度波形) ---
def process_audio_clean_balanced(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 1. 基礎降噪 (適度強度，避免聲音太假)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        # 調回 0.70，兼顧降噪與人聲自然度
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.70)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # 2. 去頭尾靜音
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]

        # 3. 溫和壓縮器
        # Threshold 調高一點點 (-28dB)，讓壓縮器不要對背景雜訊太敏感
        # Ratio 降到 4.0，讓聲音聽起來更自然，不那麼扁
        audio = audio.compress_dynamic_range(
            threshold=-28.0, 
            ratio=4.0,      
            attack=5.0, 
            release=150.0   
        )

        # 4. 【關鍵修正】保守增益
        # 從原本的 20 降到 10，大幅減少沙沙聲被放大的程度
        audio = audio + 10 

        # 5. 標準化至 -6dB
        # 雖然小聲的地方可能沒那麼「肥」，但整體聽感會乾淨很多
        audio = audio.normalize(headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except Exception as e:
        return audio_bytes

# --- Streamlit 介面邏輯 (延用穩定分類架構) ---
st.set_page_config(page_title="族語純淨音質版", layout="wide")
st.title("🎙️ 族語全自動：純淨平衡版 (減少背景沙沙聲)")

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
        def deep_scan(obj, last_title="未分類"):
            if isinstance(obj, dict):
                current_title = obj.get('listTitle') or obj.get('title') or last_title
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        path_parts = v.split('/')
                        oid = path_parts[-2] if len(path_parts) >= 2 else "others"
                        tasks.append({"url": v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}", 
                                      "parent": current_title, "child": oid, "file": os.path.basename(v)})
                    elif isinstance(v, (dict, list)): deep_scan(v, current_title)
            elif isinstance(obj, list):
                for i in obj: deep_scan(i, last_title)
        deep_scan(data)
        st.session_state.audio_tasks = tasks
        st.session_state.selected_folders = set()
        st.success(f"掃描完成！共找到 {len(tasks)} 個音檔。")
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
            btn_label = f"✅ {c_id} ({len(items)}檔)" if is_sel else f"📁 {c_id} ({len(items)}檔)"
            with cols[idx % 4]:
                if st.button(btn_label, key=f"btn_{p_name}_{c_id}"):
                    if is_sel: st.session_state.selected_folders.remove(c_id)
                    else: st.session_state.selected_folders.add(c_id)
                    st.rerun()

    final_selection = [t for t in st.session_state.audio_tasks if t['child'] in st.session_state.selected_folders]
    st.write("---")
    if st.button(f"🚀 2. 執行純淨平衡處理 ({len(final_selection)} 檔)"):
        if not final_selection: st.warning("請先選取資料夾。")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as mz:
                p_bar = st.progress(0)
                for i, task in enumerate(final_selection):
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_clean_balanced(r.content)
                            mz.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection))
            st.download_button("⬇️ 下載純淨平衡包", zip_io.getvalue(), f"{user_id}_Clean_Balanced.zip")
