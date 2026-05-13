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

# --- 1. 核心後製引擎：專業平穩化處理 ---
def process_audio_pro_stable(audio_bytes):
    try:
        # 讀取音訊 
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        
        # A. AI 降噪 (強度 0.75，比照 001.txt 規格) [cite: 3, 16]
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        y, sr = librosa.load(wav_io, sr=None)
        reduced = nr.reduce_noise(y=y, sr=sr, prop_decrease=0.75)
        
        tmp_io = io.BytesIO()
        sf.write(tmp_io, reduced, sr, format='WAV')
        tmp_io.seek(0)
        audio = AudioSegment.from_wav(tmp_io)

        # B. 去頭尾靜音 (保留 0.2s，比照 001.txt 規格) [cite: 4, 17]
        intervals = detect_nonsilent(audio, min_silence_len=300, silence_thresh=-45)
        if intervals:
            # 前後各留 200ms
            audio = audio[max(0, intervals[0][0]-200) : min(len(audio), intervals[-1][1]+200)]

        # C. 解決忽大忽小：動態範圍壓縮 (核心新增功能)
        # 這就像自動調音師，把太小的聲音拉高，太大的壓低
        audio = audio.compress_dynamic_range(
            threshold=-18.0, # 偵測門檻
            ratio=3.5,       # 壓縮比例
            attack=5.0,      # 反應速度
            release=50.0     # 釋放速度
        )

        # D. 最後峰值鎖定：-6dB (比照 001.txt 規格) [cite: 4, 17]
        # 使用 normalize 並設定 headroom 為 6.0，確保最高峰在 -6dB
        audio = audio.normalize(headroom=6.0)
        
        out_io = io.BytesIO()
        audio.export(out_io, format="mp3", bitrate="192k")
        return out_io.getvalue()
    except Exception as e:
        # 若出錯則回傳原檔，確保打包流程不中斷
        return audio_bytes

# --- 2. 介面設定與狀態管理 ---
st.set_page_config(page_title="族語分類優化專業版", layout="wide")
st.title("🎙️ 族語全自動：大單元分類 + 專業平穩後製")

if 'audio_tasks' not in st.session_state:
    st.session_state.audio_tasks = []

user_id = st.text_input("輸入帳號 ID", value="picex11301")

# --- 3. API 抓取與雙層分類邏輯 ---
if st.button("🔍 1. 抓取清單"):
    api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
    try:
        res = requests.get(api_url, timeout=15)
        data = res.json() [cite: 7, 18]
        tasks = []
        
        def scan_api(obj, p_name="未分類"):
            if isinstance(obj, dict):
                # 抓取大單元標題 listTitle [cite: 8]
                parent = obj.get('listTitle') or p_name
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}" [cite: 7, 20]
                        # 抓取路徑中的原始資料夾 ID [cite: 8, 20]
                        original_id = v.split('/')[-2] if len(v.split('/')) >= 2 else "others"
                        tasks.append({
                            "url": full_url, 
                            "parent": parent, 
                            "child": original_id, 
                            "file": os.path.basename(v)
                        })
                        # 初始化勾選狀態 [cite: 8, 21]
                        if f"chk_{full_url}" not in st.session_state:
                            st.session_state[f"chk_{full_url}"] = True
                    else:
                        scan_api(v, parent)
            elif isinstance(obj, list):
                for i in obj: scan_api(i, p_name)

        scan_api(data)
        st.session_state.audio_tasks = tasks
        st.success(f"找到 {len(tasks)} 個音檔！")
    except:
        st.error("API 連線失敗，請檢查網路或 ID。")

# --- 4. 顯示區域與穩定勾選控制 ---
if st.session_state.audio_tasks:
    # 建立樹狀結構顯示
    tree = {}
    for t in st.session_state.audio_tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)
    
    st.write("---")
    # 全域控制按鈕 [cite: 10, 23]
    ga, gn, _ = st.columns([1, 1, 8])
    if ga.button("🌐 全部全選"):
        for t in st.session_state.audio_tasks: st.session_state[f"chk_{t['url']}"] = True
        st.rerun()
    if gn.button("🌐 全部取消"):
        for t in st.session_state.audio_tasks: st.session_state[f"chk_{t['url']}"] = False
        st.rerun()

    # 渲染分類列表 [cite: 11, 24]
    for p_name in sorted(tree.keys()):
        st.header(f"📘 {p_name}")
        child_dict = tree[p_name]
        for c_id in sorted(child_dict.keys()):
            items = child_dict[c_id]
            with st.expander(f"📁 原始 ID: {c_id} (共 {len(items)} 檔)", expanded=True):
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
                        # 關鍵綁定：key 確保勾選狀態不遺失 [cite: 12, 27]
                        st.session_state[f"chk_{item['url']}"] = st.checkbox(
                            f"🎵 {item['file']}", 
                            key=f"chk_{item['url']}", 
                            value=st.session_state.get(f"chk_{item['url']}", True)
                        )

    # --- 5. 下載與後製打包 ---
    final_selection = [t for t in st.session_state.audio_tasks if st.session_state.get(f"chk_{t['url']}", False)] [cite: 13, 28]
    st.write("---")
    
    if st.button(f"🚀 2. 開始下載專業後製 ({len(final_selection)} 個)"):
        if not final_selection:
            st.warning("請先勾選音檔。")
        else:
            master_zip_io = io.BytesIO()
            with zipfile.ZipFile(master_zip_io, 'w') as master_zip: [cite: 13, 29]
                p_bar = st.progress(0)
                st_text = st.empty()
                for i, task in enumerate(final_selection):
                    st_text.text(f"正在後製平穩化: {task['file']}") [cite: 14]
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            processed = process_audio_pro_stable(r.content)
                            # 儲存結構：大單元標題 / 原始 ID / 檔名 [cite: 15, 30]
                            master_zip.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except: pass
                    p_bar.progress((i + 1) / len(final_selection)) [cite: 31]
                st_text.text("✨ 處理與打包完成！")
            
            st.download_button(
                "⬇️ 下載專業分類包", 
                master_zip_io.getvalue(), 
                f"{user_id}_Pro_Balanced.zip"
            )
