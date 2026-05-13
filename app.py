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

# --- 專業音訊引擎 ---
def process_audio_final(audio_bytes):
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
        diff = -18.0 - audio.dBFS
        audio = audio.apply_gain(diff)
        audio = audio.compress_dynamic_range(threshold=-16.0, ratio=3.0, attack=5.0, release=50.0)
        audio = effects.normalize(audio, headroom=6.0)
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 介面管理 ---
st.set_page_config(page_title="族語下載穩定版", page_icon="🎙️", layout="wide")
st.title("🎙️ 族語全自動：解決勾選失靈問題終極版")

# 1. 初始化狀態：必須確保 sel_map 與介面完全同步
if 'tasks' not in st.session_state: st.session_state.tasks = []
if 'sel_map' not in st.session_state: st.session_state.sel_map = {}

user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 1. 抓取教材層級與清單"):
    try:
        res = requests.get(f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}", timeout=15)
        data = res.json()
        new_tasks = []
        def scan(obj, list_t="課程", sub_t=""):
            if isinstance(obj, dict):
                l_title = obj.get('listTitle') or list_t
                s_title = obj.get('title') or obj.get('name') or sub_t
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        url_id = v.split('/')[-2] if len(v.split('/')) >= 2 else "unk"
                        folder = f"【{l_title}】{s_title} ({url_id})"
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        tid = f"{folder}_{os.path.basename(v)}"
                        new_tasks.append({"url": full_url, "folder": folder, "file": os.path.basename(v), "id": tid})
                        # 初始化勾選字典
                        if tid not in st.session_state.sel_map:
                            st.session_state.sel_map[tid] = True
                    else: scan(v, l_title, s_title)
            elif isinstance(obj, list):
                for i in obj: scan(i, list_t, sub_t)
        scan(data)
        st.session_state.tasks = new_tasks
        # 強制刷新 key，確保同步
        st.success("解析成功！")
    except: st.error("抓取失敗")

# --- 2. 勾選區域 (關鍵修復點) ---
if st.session_state.tasks:
    grouped = {}
    for t in st.session_state.tasks: grouped.setdefault(t['folder'], []).append(t)

    st.write("---")
    
    # 點擊按鈕直接修改字典的值，不再透過 widget 傳遞
    c_g1, c_g2, _ = st.columns([1, 1, 8])
    if c_g1.button("🌐 全部全選"):
        for tid in st.session_state.sel_map: st.session_state.sel_map[tid] = True
        st.rerun()
    if c_g2.button("🌐 全部取消"):
        for tid in st.session_state.sel_map: st.session_state.sel_map[tid] = False
        st.rerun()

    for folder in sorted(grouped.keys()):
        items = grouped[folder]
        with st.expander(f"📁 {folder}", expanded=True):
            col_ctrl1, col_ctrl2, _ = st.columns([1, 1, 8])
            if col_ctrl1.button(f"全選此層級", key=f"btn_all_{folder}"):
                for item in items: st.session_state.sel_map[item['id']] = True
                st.rerun()
            if col_ctrl2.button(f"取消此層級", key=f"btn_none_{folder}"):
                for item in items: st.session_state.sel_map[item['id']] = False
                st.rerun()
            
            st.write("")
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    # 關鍵：這裡不使用 key 直接連結 session_state
                    # 而是偵測 toggle 的變動，手動存回字典
                    tid = item['id']
                    checked = st.toggle(
                        item['file'], 
                        value=st.session_state.sel_map.get(tid, True),
                        key=f"ui_{tid}" # 這是 UI 用的 key
                    )
                    # 同步 UI 狀態到我們的邏輯字典
                    st.session_state.sel_map[tid] = checked

    # --- 3. 下載處理 ---
    final_list = [t for t in st.session_state.tasks if st.session_state.sel_map.get(t['id'], False)]
    st.write("---")
    if st.button(f"🚀 2. 執行後製並打包 ({len(final_list)} 個)"):
        if not final_list:
            st.warning("請先勾選音檔")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                p_bar = st.progress(0)
                msg = st.empty()
                for i, task in enumerate(final_list):
                    msg.text(f"處理中: {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_final(r.content)
                            zf.writestr(f"{task['folder']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_list))
                msg.text("✨ 完成！")
            st.download_button("⬇️ 下載專業分類包", zip_io.getvalue(), f"{user_id}_Final.zip")
