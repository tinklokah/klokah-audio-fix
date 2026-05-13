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

# --- 專業音訊處理 (與本地 v3.6 核心邏輯一致) ---
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

        # 3. 響度平衡 (-18 dBFS) 與 厚度壓縮 (模擬 Loudnorm)
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

# --- UI 管理與狀態函數 ---
st.set_page_config(page_title="族語教材精準分類器", page_icon="🗂️", layout="wide")
st.title("🗂️ 族語全自動：教材層級細分與專業後製")

if 'tasks' not in st.session_state: st.session_state.tasks = []
if 'sel' not in st.session_state: st.session_state.sel = {}

def update_sel(task_ids, value):
    for tid in task_ids: st.session_state.sel[tid] = value

user_id = st.text_input("輸入帳號 ID (例如: picex11301)", value="picex11301")

if st.button("🔍 1. 抓取教材層級與清單"):
    try:
        res = requests.get(f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}", timeout=15)
        data = res.json()
        new_tasks = []

        # 深度掃描函數：追蹤 listTitle 和當前標題
        def deep_scan(obj, list_title="未知大單元", sub_title=""):
            if isinstance(obj, dict):
                # 更新層級名稱
                l_title = obj.get('listTitle') or list_title
                s_title = obj.get('title') or obj.get('name') or sub_title
                
                # 組合顯示資料夾名稱：[大單元名稱] 小單元名稱 (網址ID)
                # 例如：[01-來唱我們的歌吧] 序 (70284)
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        # 從網址提取 ID 作為備份標籤
                        path_parts = v.split('/')
                        url_id = path_parts[-2] if len(path_parts) >= 2 else "unk"
                        
                        folder_name = f"【{l_title}】{s_title} ({url_id})"
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        tid = f"{folder_name}_{os.path.basename(v)}"
                        
                        new_tasks.append({
                            "url": full_url, 
                            "folder": folder_name, 
                            "file": os.path.basename(v), 
                            "id": tid
                        })
                        if tid not in st.session_state.sel: st.session_state.sel[tid] = True
                    else:
                        deep_scan(v, l_title, s_title)
            elif isinstance(obj, list):
                for item in obj: deep_scan(item, list_title, sub_title)

        deep_scan(data)
        st.session_state.tasks = new_tasks
        st.success(f"解析成功！共找到 {len(new_tasks)} 個音檔。")
    except Exception as e:
        st.error(f"解析失敗: {e}")

# --- 顯示層級分組 ---
if st.session_state.tasks:
    grouped = {}
    for t in st.session_state.tasks: grouped.setdefault(t['folder'], []).append(t)

    st.write("---")
    all_ids = [t['id'] for t in st.session_state.tasks]
    c_g1, c_g2, _ = st.columns([1, 1, 8])
    c_g1.button("🌐 全部全選", on_click=update_sel, args=(all_ids, True))
    c_g2.button("🌐 全部取消", on_click=update_sel, args=(all_ids, False))

    for folder_name in sorted(grouped.keys()):
        items = grouped[folder_name]
        folder_ids = [i['id'] for i in items]
        
        with st.expander(f"📁 {folder_name}", expanded=True):
            c1, c2, _ = st.columns([1, 1, 8])
            c1.button(f"勾選此層級", key=f"all_{folder_name}", on_click=update_sel, args=(folder_ids, True))
            c2.button(f"取消此層級", key=f"none_{folder_name}", on_click=update_sel, args=(folder_ids, False))
            
            st.write("---")
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    st.session_state.sel[item['id']] = st.checkbox(
                        item['file'], 
                        value=st.session_state.sel.get(item['id'], True), 
                        key=f"cb_{item['id']}"
                    )

    final_list = [t for t in st.session_state.tasks if st.session_state.sel.get(t['id'])]
    st.write("---")
    if st.button(f"🚀 2. 開始後製打包 ({len(final_list)} 個)"):
        if not final_list:
            st.warning("請勾選音檔")
        else:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                prog = st.progress(0)
                msg = st.empty()
                for i, task in enumerate(final_list):
                    msg.text(f"正在後製 (-6dB 峰值): {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            # 執行專業後製
                            processed = process_audio_final(r.content)
                            # 存入對應名稱的資料夾
                            zip_file.writestr(f"{task['folder']}/{task['file']}", processed)
                    except: pass
                    prog.progress((i + 1) / len(final_list))
                msg.text("✨ 教材後製打包完成！")
            st.download_button("⬇️ 下載最終分類包", zip_buffer.getvalue(), f"{user_id}_Categorized_Pro.zip")
