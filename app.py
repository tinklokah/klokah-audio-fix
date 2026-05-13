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

# --- 專業音訊處理 (降噪 0.75, 響度 -18dB, 峰值 -6dB) ---
def process_audio_final(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 1. AI 降噪 (0.75)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # 2. 去頭尾靜音 (前後 0.2s)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]

        # 3. 響度平衡 (-18 dBFS) 與 厚度壓縮
        diff = -18.0 - audio.dBFS
        audio = audio.apply_gain(diff)
        audio = audio.compress_dynamic_range(threshold=-16.0, ratio=3.0, attack=5.0, release=50.0)

        # 4. 強制峰值鎖定 -6dB
        audio = effects.normalize(audio, headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- UI 與狀態更新邏輯 ---
st.set_page_config(page_title="族語教材精準下載器", page_icon="🗂️", layout="wide")
st.title("🗂️ 族語全自動：穩定勾選與層級分類版")

# 初始化狀態
if 'tasks' not in st.session_state: st.session_state.tasks = []
if 'sel_dict' not in st.session_state: st.session_state.sel_dict = {}

# 更新狀態用的 Callback
def sync_selection(tids, val):
    for tid in tids:
        st.session_state.sel_dict[tid] = val

user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 1. 抓取教材層級清單"):
    try:
        res = requests.get(f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}", timeout=15)
        data = res.json()
        new_tasks = []

        def scan(obj, list_t="未知大單元", sub_t=""):
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
                        # 預設勾選
                        if tid not in st.session_state.sel_dict:
                            st.session_state.sel_dict[tid] = True
                    else:
                        scan(v, l_title, s_title)
            elif isinstance(obj, list):
                for i in obj: scan(i, list_t, sub_t)

        scan(data)
        st.session_state.tasks = new_tasks
        st.success(f"解析成功！共 {len(new_tasks)} 個音檔。")
    except: st.error("API 解析失敗")

# --- 顯示層級與穩定勾選 ---
if st.session_state.tasks:
    grouped = {}
    for t in st.session_state.tasks: grouped.setdefault(t['folder'], []).append(t)

    st.write("---")
    all_ids = [t['id'] for t in st.session_state.tasks]
    c_g1, c_g2, _ = st.columns([1, 1, 8])
    c_g1.button("🌐 全部選取", on_click=sync_selection, args=(all_ids, True))
    c_g2.button("🌐 全部取消", on_click=sync_selection, args=(all_ids, False))

    for folder in sorted(grouped.keys()):
        items = grouped[folder]
        item_ids = [i['id'] for i in items]
        
        with st.expander(f"📁 {folder}", expanded=True):
            b1, b2, _ = st.columns([1, 1, 8])
            b1.button(f"全選此單元", key=f"all_{folder}", on_click=sync_selection, args=(item_ids, True))
            b2.button(f"清空此單元", key=f"none_{folder}", on_click=sync_selection, args=(item_ids, False))
            
            st.write("")
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    # 改用 toggle 且手動綁定狀態
                    # 使用 session_state 直接作為存儲，避免 checkbox 狀態跑掉
                    st.session_state.sel_dict[item['id']] = st.toggle(
                        item['file'], 
                        value=st.session_state.sel_dict.get(item['id'], True),
                        key=f"tg_{item['id']}"
                    )

    # 執行下載
    final_list = [t for t in st.session_state.tasks if st.session_state.sel_dict.get(t['id'])]
    st.write("---")
    if st.button(f"🚀 2. 開始後製打包 ({len(final_list)} 個)"):
        if not final_list:
            st.warning("尚未選擇檔案")
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
                msg.text("✨ 打包完成！")
            st.download_button("⬇️ 下載專業平衡包", zip_io.getvalue(), f"{user_id}_Categorized.zip")
