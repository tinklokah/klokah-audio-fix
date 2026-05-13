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

# --- 1. 專業音訊處理引擎 (移植自 v3.6 核心) ---
def process_audio_final(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # 1. AI 降噪 (比照本地腳本參數 0.75)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # 2. 去頭尾靜音 (偵測後前後保留 200ms)
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            start_trim = max(0, intervals[0][0] - 200)
            end_trim = min(len(audio), intervals[-1][1] + 200)
            audio = audio[start_trim:end_trim]

        # 3. 響度平衡與增加厚度 (目標 -18 dBFS RMS)
        diff = -18.0 - audio.dBFS
        audio = audio.apply_gain(diff)
        
        # 4. 動態壓縮 (建立像 loudnorm 的厚實感)
        audio = audio.compress_dynamic_range(threshold=-16.0, ratio=3.0, attack=5.0, release=50.0)

        # 5. 強制峰值鎖定在 -6dB (Headroom 6.0)
        audio = effects.normalize(audio, headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        # 若處理出錯則回傳原檔
        return audio_bytes

# --- 2. 狀態管理函數 (解決勾選失效的關鍵) ---
def sync_selection(ids, value):
    for tid in ids:
        st.session_state.sel_map[tid] = value

# --- 3. 網頁 UI 設置 ---
st.set_page_config(page_title="族語教材專業下載器", page_icon="🎙️", layout="wide")
st.title("🎙️ 族語全自動：專業後製與教材層級細分版")

# 初始化 Session State
if 'tasks' not in st.session_state: st.session_state.tasks = []
if 'sel_map' not in st.session_state: st.session_state.sel_map = {}

user_id = st.text_input("輸入帳號 ID (例如: picex11301)", value="picex11301")

if st.button("🔍 1. 抓取教材層級與清單"):
    try:
        res = requests.get(f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}", timeout=15)
        data = res.json()
        new_tasks = []

        # 深度遞迴掃描：保留大單元名稱 (listTitle)
        def deep_scan(obj, list_t="未知課程", sub_t=""):
            if isinstance(obj, dict):
                l_title = obj.get('listTitle') or list_t
                s_title = obj.get('title') or obj.get('name') or sub_t
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        url_id = v.split('/')[-2] if len(v.split('/')) >= 2 else "unk"
                        # 格式化資料夾名稱
                        folder = f"【{l_title}】{s_title} ({url_id})"
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        tid = f"{folder}_{os.path.basename(v)}"
                        
                        new_tasks.append({
                            "url": full_url, "folder": folder, "file": os.path.basename(v), "id": tid
                        })
                        # 預設勾選
                        if tid not in st.session_state.sel_map:
                            st.session_state.sel_map[tid] = True
                    else:
                        deep_scan(v, l_title, s_title)
            elif isinstance(obj, list):
                for i in obj: deep_scan(i, list_t, sub_t)

        deep_scan(data)
        st.session_state.tasks = new_tasks
        st.success(f"解析成功！共找到 {len(new_tasks)} 個音檔。")
    except:
        st.error("API 連線或解析失敗。")

# --- 4. 勾選清單顯示區域 ---
if st.session_state.tasks:
    grouped = {}
    for t in st.session_state.tasks: grouped.setdefault(t['folder'], []).append(t)

    st.write("---")
    # 全域快速操作
    all_ids = [t['id'] for t in st.session_state.tasks]
    c_g1, c_g2, _ = st.columns([1, 1, 8])
    c_g1.button("🌐 全部全選", on_click=sync_selection, args=(all_ids, True))
    c_g2.button("🌐 全部取消", on_click=sync_selection, args=(all_ids, False))

    # 按資料夾（單元）分組顯示
    for folder_name in sorted(grouped.keys()):
        items = grouped[folder_name]
        item_ids = [i['id'] for i in items]
        
        with st.expander(f"📁 {folder_name}", expanded=True):
            # 單元級別全選按鈕
            c1, c2, _ = st.columns([1, 1, 8])
            c1.button(f"勾選此層級", key=f"all_{folder_name}", on_click=sync_selection, args=(item_ids, True))
            c2.button(f"取消此層級", key=f"none_{folder_name}", on_click=sync_selection, args=(item_ids, False))
            
            st.write("")
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    # 使用 toggle 替代 checkbox，提高穩定性
                    # key 直接連結到字典，確保狀態不丟失
                    st.session_state.sel_map[item['id']] = st.toggle(
                        item['file'], 
                        value=st.session_state.sel_map.get(item['id'], True),
                        key=f"tg_{item['id']}"
                    )

    # --- 5. 後製與打包下載 ---
    final_list = [t for t in st.session_state.tasks if st.session_state.sel_map.get(t['id'])]
    st.write("---")
    
    if st.button(f"🚀 2. 執行 AI 專業後製並打包 ({len(final_list)} 個)"):
        if not final_list:
            st.warning("請先勾選音檔。")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                p_bar = st.progress(0)
                msg = st.empty()
                for i, task in enumerate(final_list):
                    msg.text(f"處理中 (鎖定 -6dB 峰值): {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_final(r.content)
                            zf.writestr(f"{task['folder']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_list))
                msg.text("✨ 專業後製打包完成！")
            
            st.download_button(
                label="⬇️ 下載最終分類優化包",
                data=zip_io.getvalue(),
                file_name=f"{user_id}_Final_Pro.zip",
                mime="application/zip"
            )
