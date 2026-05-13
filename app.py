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

# --- 核心後製引擎 ---
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
st.set_page_config(page_title="族語分類優化專業版", layout="wide")
st.title("🎙️ 族語全自動：大單元分類 + 專業平穩後製")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []
if 'check_states' not in st.session_state:
    st.session_state.check_states = {}

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
                        tasks.append({"url": full_url, "parent": parent, "child": original_id, "file": os.path.basename(v)})
                        # 初始狀態存在 check_states 裡
                        if full_url not in st.session_state.check_states:
                            st.session_state.check_states[full_url] = True
                    else:
                        scan_api(v, parent)
            elif isinstance(obj, list):
                for i in obj: scan_api(i, p_name)
        scan_api(data)
        st.session_state.audio_tasks = tasks
        st.success(f"找到 {len(tasks)} 個音檔！")
    except:
        st.error("API 連線失敗")

# --- 4. 顯示與勾選邏輯 ---
if st.session_state.audio_tasks:
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    
    st.write("---")
    # 全選 / 取消按鈕邏輯
    ga, gn, _ = st.columns([1, 1, 8])
    if ga.button("🌐 全部全選"):
        for t in st.session_state.audio_tasks:
            st.session_state.check_states[t['url']] = True
        st.rerun()
    if gn.button("🌐 全部取消"):
        for t in st.session_state.audio_tasks:
            st.session_state.check_states[t['url']] = False
        st.rerun()

    for p_name in sorted(tree.keys()):
        st.header(f"📘 {p_name}")
        for c_id in sorted(tree[p_name].keys()):
            items = tree[p_name][c_id]
            with st.expander(f"📁 原始 ID: {c_id} (共 {len(items)} 檔)", expanded=True):
                ca, cn, _ = st.columns([1, 1, 8])
                if ca.button(f"全選 {c_id}", key=f"all_{p_name}_{c_id}"):
                    for i in items: st.session_state.check_states[i['url']] = True
                    st.rerun()
                if cn.button(f"清空 {c_id}", key=f"none_{p_name}_{c_id}"):
                    for i in items: st.session_state.check_states[i['url']] = False
                    st.rerun()
                
                cols = st.columns(3)
                for idx, item in enumerate(items):
                    with cols[idx % 3]:
                        # 使用 check_states 作為唯一真實來源
                        is_checked = st.checkbox(
                            f"🎵 {item['file']}", 
                            value=st.session_state.check_states.get(item['url'], True),
                            key=f"cb_{item['url']}"
                        )
                        # 即時更新狀態，避免重整後勾選消失
                        st.session_state.check_states[item['url']] = is_checked

    # --- 5. 下載 ---
    # 過濾出有勾選的任務
    final_selection = [t for t in st.session_state.audio_tasks if st.session_state.check_states.get(t['url'], False)]
    
    st.write("---")
    if st.button(f"🚀 2. 開始下載專業後製 ({len(final_selection)} 個)"):
        if not final_selection:
            st.warning("請先勾選音檔。")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                st_text = st.empty()
                for i, task in enumerate(final_selection):
                    st_text.text(f"正在後製平穩化: {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_pro_stable(r.content)
                            master_zip.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection))
                st_text.text("✨ 處理與打包完成！")
            
            st.download_button(
                "⬇️ 下載專業分類包", 
                master_zip_io.getvalue(), 
                f"{user_id}_Pro_Fixed.zip"
            )
