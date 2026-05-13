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
def process_audio_final(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # A. AI 降噪 (0.75)
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
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]

        # C. 響度與厚度 (-18 dBFS, Compressor)
        diff = -18.0 - audio.dBFS
        audio = audio.apply_gain(diff)
        audio = audio.compress_dynamic_range(threshold=-16.0, ratio=3.0, attack=5.0, release=50.0)

        # D. 強制峰值鎖定 -6dB
        audio = effects.normalize(audio, headroom=6.0)

        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except:
        return audio_bytes

# --- 2. 狀態管理 ---
st.set_page_config(page_title="族語教材專業打包", layout="wide")
st.title("🎙️ 族語全自動：原始路徑分類與音質優化版")

if 'tasks' not in st.session_state: st.session_state.tasks = []
if 'sel_dict' not in st.session_state: st.session_state.sel_dict = {}

def update_selection(ids, value):
    for tid in ids: st.session_state.sel_dict[tid] = value

# --- 3. API 解析 (保持原始資料夾名稱) ---
user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 抓取教材層級"):
    try:
        api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
        res = requests.get(api_url, timeout=15)
        data = res.json()
        
        new_tasks = []
        def scan_api(obj, p_folder="未分類"):
            if isinstance(obj, dict):
                # 大單元標題
                parent = obj.get('listTitle') or p_folder
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        # 關鍵：提取原始資料夾名稱 (如 70284)
                        path_parts = v.split('/')
                        original_subfolder = path_parts[-2] if len(path_parts) >= 2 else "unknown"
                        
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        filename = os.path.basename(v)
                        tid = f"{parent}_{original_subfolder}_{filename}"
                        
                        new_tasks.append({
                            "id": tid,
                            "url": full_url,
                            "parent": parent,            # 大資料夾 (課程標題)
                            "child": original_subfolder,  # 子資料夾 (原始 ID 名稱)
                            "file": filename
                        })
                        if tid not in st.session_state.sel_dict:
                            st.session_state.sel_dict[tid] = True
                    else:
                        scan_api(v, parent)
            elif isinstance(obj, list):
                for item in obj: scan_api(item, p_folder)

        scan_api(data)
        st.session_state.tasks = new_tasks
        st.success(f"抓取完成，共 {len(new_tasks)} 個檔案。")
    except Exception as e:
        st.error(f"解析失敗: {e}")

# --- 4. 顯示與勾選 ---
if st.session_state.tasks:
    # 建立樹狀結構：Parent -> Child -> Files
    tree = {}
    for t in st.session_state.tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)

    st.write("---")
    all_ids = [t['id'] for t in st.session_state.tasks]
    ca, cn, _ = st.columns([1, 1, 8])
    ca.button("🌐 全部全選", on_click=update_selection, args=(all_ids, True))
    cn.button("🌐 全部取消", on_click=update_selection, args=(all_ids, False))

    for p_name in sorted(tree.keys()):
        st.subheader(f"📘 {p_name}")
        children = tree[p_name]
        for c_name in sorted(children.keys()):
            items = children[c_name]
            item_ids = [i['id'] for i in items]
            
            with st.expander(f"└─ 📁 原始路徑: {c_name} ({len(items)} 檔)", expanded=True):
                b1, b2, _ = st.columns([1, 1, 8])
                b1.button("全選單元", key=f"all_{p_name}_{c_name}", on_click=update_selection, args=(item_ids, True))
                b2.button("清空單元", key=f"none_{p_name}_{c_name}", on_click=update_selection, args=(item_ids, False))
                
                cols = st.columns(3)
                for idx, item in enumerate(items):
                    with cols[idx % 3]:
                        st.session_state.sel_dict[item['id']] = st.checkbox(
                            item['file'],
                            value=st.session_state.sel_dict.get(item['id'], True),
                            key=f"cb_{item['id']}"
                        )
        st.write("---")

    # --- 5. 執行下載打包 ---
    final_list = [t for t in st.session_state.tasks if st.session_state.sel_dict.get(t['id'])]
    if st.button(f"🚀 2. 開始 AI 後製並打包下載 ({len(final_list)} 個)"):
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
                            # 建立目錄結構：大單元標題/原始路徑ID/檔名
                            save_path = f"{task['parent']}/{task['child']}/{task['file']}"
                            zf.writestr(save_path, processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_list))
                msg.text("✨ 處理完成！")
            st.download_button("⬇️ 下載專業分類包", zip_io.getvalue(), f"{user_id}_Final.zip")
